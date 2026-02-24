import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { TeamManager } from '../../../utils/team-manager'
import { GroupTypeManager } from '../../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../../worker/ingestion/persons/persons-store'
import { EventPipelineRunnerOptions } from '../../event-processing/event-pipeline-options'
import { AiEventOutput, IngestionOutputs } from '../../event-processing/ingestion-outputs'
import { TopHogWrapper } from '../../pipelines/extensions/tophog'

export interface AiEventSubpipelineConfig {
    options: EventPipelineRunnerOptions
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
    outputs: IngestionOutputs<AiEventOutput>
    groupId: string
    topHog: TopHogWrapper
}
