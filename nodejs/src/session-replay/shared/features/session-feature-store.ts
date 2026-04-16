import { KafkaProducerWrapper } from '../../../kafka/producer'
import { FeatureEndResult } from '../../../session-recording/sessions/session-feature-recorder'
import { TimestampFormat } from '../../../types'
import { logger } from '../../../utils/logger'
import { castTimestampOrNow } from '../../../utils/utils'

export interface SessionFeatureBlock {
    sessionId: string
    teamId: number
    distinctId: string
    batchId: string
    features: FeatureEndResult
    isDeleted?: boolean
}

export interface DeletionFeatureBlock {
    sessionId: string
    teamId: number
}

export class SessionFeatureStore {
    constructor(
        private producer: KafkaProducerWrapper,
        private kafkaTopic: string,
        private enabled: boolean = false
    ) {
        logger.debug('🧠', 'session_feature_store_created', { enabled })
    }

    public async storeSessionFeatures(blocks: SessionFeatureBlock[]): Promise<void> {
        if (!this.enabled || blocks.length === 0) {
            return
        }

        logger.info('🧠', 'session_feature_store_storing', { count: blocks.length })

        const events = blocks.map((block) => ({
            session_id: block.sessionId,
            team_id: block.teamId,
            distinct_id: block.distinctId,
            batch_id: block.batchId,
            first_timestamp: castTimestampOrNow(block.features.startDateTime, TimestampFormat.ClickHouse),
            last_timestamp: castTimestampOrNow(block.features.endDateTime, TimestampFormat.ClickHouse),
            event_count: block.features.eventCount,
            mouse_position_count: block.features.mousePositionCount,
            mouse_sum_x: block.features.mouseSumX,
            mouse_sum_x_squared: block.features.mouseSumXSquared,
            mouse_sum_y: block.features.mouseSumY,
            mouse_sum_y_squared: block.features.mouseSumYSquared,
            mouse_distance_traveled: block.features.mouseDistanceTraveled,
            mouse_direction_change_count: block.features.mouseDirectionChangeCount,
            mouse_velocity_sum: block.features.mouseVelocitySum,
            mouse_velocity_sum_of_squares: block.features.mouseVelocitySumOfSquares,
            mouse_velocity_count: block.features.mouseVelocityCount,
            scroll_event_count: block.features.scrollEventCount,
            total_scroll_magnitude: block.features.totalScrollMagnitude,
            scroll_direction_reversal_count: block.features.scrollDirectionReversalCount,
            rapid_scroll_reversal_count: block.features.rapidScrollReversalCount,
            click_count: block.features.clickCount,
            keypress_count: block.features.keypressCount,
            mouse_activity_count: block.features.mouseActivityCount,
            rage_click_count: block.features.rageClickCount,
            dead_click_count: block.features.deadClickCount,
            inter_action_gap_count: block.features.interActionGapCount,
            inter_action_gap_sum_ms: block.features.interActionGapSumMs,
            inter_action_gap_sum_of_squares_ms: block.features.interActionGapSumOfSquaresMs,
            max_idle_gap_ms: block.features.maxIdleGapMs,
            quick_back_count: block.features.quickBackCount,
            page_visit_count: block.features.pageVisitCount,
            visited_urls: block.features.visitedUrls,
            console_error_count: block.features.consoleErrorCount,
            console_error_after_click_count: block.features.consoleErrorAfterClickCount,
            network_request_count: block.features.networkRequestCount,
            network_failed_request_count: block.features.networkFailedRequestCount,
            network_request_duration_sum: block.features.networkRequestDurationSum,
            network_request_duration_sum_of_squares: block.features.networkRequestDurationSumOfSquares,
            network_request_duration_count: block.features.networkRequestDurationCount,
            max_scroll_y: block.features.maxScrollY,
            click_target_ids: block.features.clickTargetIds,
            text_selection_count: block.features.textSelectionCount,
            is_deleted: block.isDeleted ? 1 : 0,
        }))

        await this.producer.queueMessages({
            topic: this.kafkaTopic,
            messages: events.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        await this.producer.flush()

        logger.info('🧠', 'session_feature_store_stored', { count: events.length })
    }

    public async storeDeletionMarkers(blocks: DeletionFeatureBlock[]): Promise<void> {
        const events = blocks.map((block) => ({
            session_id: block.sessionId,
            team_id: block.teamId,
            is_deleted: 1,
        }))

        await this.producer.queueMessages({
            topic: this.kafkaTopic,
            messages: events.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        await this.producer.flush()

        logger.info('🧠', 'session_feature_store_deletion_markers_stored', { count: events.length })
    }
}
