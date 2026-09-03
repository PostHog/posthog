import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { canvasActivityDescriber } from './activityDescriber'

const getTextContent = (describer: { description: JSX.Element | string | null }): string => {
    if (!describer.description || typeof describer.description === 'string') {
        return (describer.description as string) || ''
    }
    const { container } = render(describer.description)
    return container.textContent || ''
}

const canvasLogItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
    activity: 'published',
    created_at: '2026-08-06T10:00:00Z',
    scope: 'Canvas',
    item_id: 'canvas-uuid',
    detail: { merge: null, trigger: null, changes: null, name: 'Signups board' },
    ...overrides,
})

const capabilitiesChange = (before: unknown, after: unknown): ActivityChange => ({
    type: ActivityScope.CANVAS,
    action: 'changed',
    field: 'capabilities',
    before: before as ActivityChange['before'],
    after: after as ActivityChange['after'],
})

describe('canvasActivityDescriber', () => {
    it('summarizes a first publish with a null previous manifest', () => {
        const text = getTextContent(
            canvasActivityDescriber(
                canvasLogItem({
                    detail: {
                        merge: null,
                        trigger: null,
                        name: 'Signups board',
                        changes: [
                            capabilitiesChange(null, {
                                posthog: { insights: ['abc123'], inlineQueries: true, captureEvents: [] },
                            }),
                        ],
                    },
                })
            )
        )
        expect(text).toContain('published canvas Signups board')
        expect(text).toContain('declared insight abc123')
        expect(text).toContain('enabled inline queries')
    })

    it('summarizes added and removed capabilities between two manifests', () => {
        const text = getTextContent(
            canvasActivityDescriber(
                canvasLogItem({
                    detail: {
                        merge: null,
                        trigger: null,
                        name: 'Signups board',
                        changes: [
                            capabilitiesChange(
                                {
                                    posthog: {
                                        insights: ['abc123'],
                                        inlineQueries: true,
                                        captureEvents: ['clicked'],
                                    },
                                },
                                {
                                    posthog: {
                                        insights: ['def456'],
                                        inlineQueries: false,
                                        captureEvents: ['clicked'],
                                    },
                                }
                            ),
                        ],
                    },
                })
            )
        )
        expect(text).toContain('declared insight def456')
        expect(text).toContain('removed insight abc123')
        expect(text).toContain('disabled inline queries')
        expect(text).not.toContain('clicked')
    })

    it('describes a publish without capability changes as a plain publish', () => {
        const text = getTextContent(canvasActivityDescriber(canvasLogItem({})))
        expect(text).toContain('published canvas Signups board')
        expect(text).not.toContain('capabilities')
    })

    it('summarizes a draft and the capabilities it would add', () => {
        const text = getTextContent(
            canvasActivityDescriber(
                canvasLogItem({
                    activity: 'drafted',
                    detail: {
                        merge: null,
                        trigger: null,
                        name: 'Signups board',
                        changes: [
                            capabilitiesChange(
                                { posthog: { insights: [], inlineQueries: false, captureEvents: [] } },
                                { posthog: { insights: ['abc123'], inlineQueries: false, captureEvents: [] } }
                            ),
                        ],
                    },
                })
            )
        )
        expect(text).toContain('drafted a new version of canvas Signups board')
        expect(text).toContain('declared insight abc123')
        expect(text).not.toContain('published')
    })

    it.each([
        [
            'name',
            { type: ActivityScope.CANVAS, action: 'changed', field: 'name', before: 'Old', after: 'New' },
            'renamed it from Old to New',
        ],
        [
            'pinned',
            { type: ActivityScope.CANVAS, action: 'changed', field: 'pinned', before: false, after: true },
            'pinned it to its channel',
        ],
    ] as [string, ActivityChange, string][])('describes an update to %s', (_field, change, expected) => {
        const text = getTextContent(
            canvasActivityDescriber(
                canvasLogItem({
                    activity: 'updated',
                    detail: { merge: null, trigger: null, name: 'Signups board', changes: [change] },
                })
            )
        )
        expect(text).toContain(expected)
    })
})
