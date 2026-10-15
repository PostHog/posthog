import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'

import { V4JobAdmission } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/job-admission'
import { V4_IMAGE_FETCH_LANE, v4HostLimits } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/lane'
import { RawImageStore } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/raw-image-store'
import { SharedImageFetcher } from '~/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/shared-image-fetcher'
import { TeamDayKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-day-keys'
import { FrontierPublisher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/frontier-publisher'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { IngestionSessionReplayMlImageFetchRetryServer } from './ingestion-session-replay-ml-image-fetch-retry-server'
import {
    ImageFetchLane,
    ImageFetchLaneParts,
    IngestionSessionReplayMlImageFetchServer,
    v3HostLimits,
} from './ingestion-session-replay-ml-image-fetch-server'
import { IngestionSessionReplayMlMirrorServerConfig } from './ml-mirror-server-config'

/** The v4 series carry this label, and v3 series keep their labels unchanged. */
const V4_METRIC_LABELS = { ml_image_fetch_lane: 'v4' }

/** A v4 pod in the v3 group would take v3 partitions and read none of their topics. */
function assertOwnGroup(config: IngestionSessionReplayMlMirrorServerConfig): void {
    const group = config.AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_GROUP_ID
    if (!group || group === config.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID) {
        throw new Error('AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_GROUP_ID must be set and differ from the v3 lane group')
    }
}

/**
 * The v4 image fetch lane: the v3 fetch policy over the v4 recorder's URLs, storing each image sealed and unscrubbed in
 * `images-v4`. It reads the team day keys and never writes them, and it uses a share of the v3 per-host limits.
 */
export class IngestionSessionReplayMlImageFetchV4Server extends IngestionSessionReplayMlImageFetchServer {
    protected override readonly lane: ImageFetchLane = V4_IMAGE_FETCH_LANE
    protected override readonly metricLabels: Record<string, string> = V4_METRIC_LABELS

    protected override buildLaneParts(_publisher: FrontierPublisher): Promise<ImageFetchLaneParts> {
        assertOwnGroup(this.config)
        const {
            AI_RESEARCH_REPLAY_V4_KEY_TABLE,
            AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN,
            AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET,
        } = this.config
        if (
            !AI_RESEARCH_REPLAY_V4_KEY_TABLE ||
            !AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN ||
            !AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET
        ) {
            throw new Error(
                'the v4 image fetch lane needs AI_RESEARCH_REPLAY_V4_KEY_TABLE, AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN and AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET'
            )
        }
        const s3 = buildSessionRecordingS3Client(this.config)
        if (!s3) {
            throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the v4 image fetch lane')
        }
        const region = this.config.SESSION_RECORDING_V2_S3_REGION || 'us-east-1'
        const keys = new TeamDayKeys(
            new DynamoDBClient({ region, endpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT, maxAttempts: 5 }),
            new KMSClient({ region, maxAttempts: 3 }),
            AI_RESEARCH_REPLAY_V4_KEY_TABLE,
            AI_RESEARCH_REPLAY_V4_KMS_KEY_ARN,
            this.config.AI_RESEARCH_REPLAY_KMS_REQUESTS_PER_SECOND
        )
        const admission = new V4JobAdmission(keys, this.config.AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_MAX_REF_AGE_DAYS)
        return Promise.resolve({
            imageSink: new RawImageStore(
                keys,
                s3,
                AI_RESEARCH_REPLAY_V4_IMAGES_BUCKET,
                this.config.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_PENDING_PUBLISHES
            ),
            admitCandidates: (candidates, nowMs) => admission.admit(candidates, nowMs),
            hostLimits: v4HostLimits(
                v3HostLimits(this.config),
                this.config.AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_HOST_BUDGET_SHARE
            ),
            wrapFetcher: (fetcher) => new SharedImageFetcher(fetcher),
        })
    }
}

/** Relays the v4 lane's delay tiers back to its frontier. */
export class IngestionSessionReplayMlImageFetchV4RetryServer extends IngestionSessionReplayMlImageFetchRetryServer {
    protected override readonly lane: ImageFetchLane = V4_IMAGE_FETCH_LANE
    protected override readonly metricLabels: Record<string, string> = V4_METRIC_LABELS

    protected override async startServices(): Promise<void> {
        assertOwnGroup(this.config)
        return super.startServices()
    }
}
