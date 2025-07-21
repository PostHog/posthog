import { Message } from 'node-rdkafka'

import { applyDropEventsRestrictions } from '../../../src/ingestion/event-preprocessing/apply-drop-events-restrictions'
import { EventIngestionRestrictionManager } from '../../../src/utils/event-ingestion-restriction-manager'
import { getMetricValues, resetMetrics } from '../../helpers/metrics'

describe('applyDropEventsRestrictions', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

    beforeEach(() => {
        resetMetrics()
        eventIngestionRestrictionManager = {
            shouldDropEvent: jest.fn(),
        } as unknown as EventIngestionRestrictionManager
    })

    it('should return message when token is present and not dropped', () => {
        const message = {
            headers: [{ token: Buffer.from('valid-token-123') }, { distinct_id: Buffer.from('user-456') }],
        } as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toBe(message)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith('valid-token-123', 'user-456')
    })

    it('should return null when token is present but should be dropped', () => {
        const message = {
            headers: [{ token: Buffer.from('blocked-token-abc') }, { distinct_id: Buffer.from('blocked-user-def') }],
        } as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

        const result = applyDropEventsRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toBeNull()
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
            'blocked-token-abc',
            'blocked-user-def'
        )
    })

    it('should handle message without headers', () => {
        const message = {} as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toBe(message)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined)
    })

    it('should handle message with empty headers', () => {
        const message = { headers: [] } as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(false)

        const result = applyDropEventsRestrictions(message, eventIngestionRestrictionManager)

        expect(result).toBe(message)
        expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(undefined, undefined)
    })

    it('should increment metrics when dropping events', async () => {
        const message = {
            headers: [{ token: Buffer.from('metrics-token-xyz') }, { distinct_id: Buffer.from('metrics-user-123') }],
        } as unknown as Message
        jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

        applyDropEventsRestrictions(message, eventIngestionRestrictionManager)

        const metrics = await getMetricValues('ingestion_event_dropped_total')
        expect(metrics).toEqual([
            {
                labels: {
                    drop_cause: 'blocked_token',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
    })
})
