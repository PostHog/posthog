import { expectLogic } from 'kea-test-utils'

import type { AttachedContextItem } from '~/layout/ai/attachedContext'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { initKeaTests } from '~/test/init'

describe('attachedContextLogic', () => {
    let logic: ReturnType<typeof attachedContextLogic.build>

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        logic = attachedContextLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('registers and upserts a provider, and deregisters it', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', [{ type: 'insight', key: 'a', label: 'A' }])
        }).toMatchValues({ contextItems: [{ type: 'insight', key: 'a', label: 'A' }], hasContext: true })

        // Re-register the same provider replaces its items (upsert).
        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', [{ type: 'dashboard', key: 1 }])
        }).toMatchValues({ contextItems: [{ type: 'dashboard', key: 1 }] })

        await expectLogic(logic, () => {
            logic.actions.deregisterContext('scene')
        }).toMatchValues({ contextItems: [], hasContext: false })
    })

    it('dedupes across providers by `${type}:${key ?? value}` (first writer wins)', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('p1', [{ type: 'insight', key: 'x', label: 'first' }])
            logic.actions.registerContext('p2', [
                { type: 'insight', key: 'x', label: 'second' },
                { type: 'dashboard', key: 9 },
            ])
        }).toMatchValues({
            contextItems: [
                { type: 'insight', key: 'x', label: 'first' },
                { type: 'dashboard', key: 9 },
            ],
        })
    })

    it('drops items with neither key nor value', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerContext('p', [{ type: 'insight' }, { type: 'text', value: 'keep me' }])
        }).toMatchValues({ contextItems: [{ type: 'text', value: 'keep me' }] })
    })

    // Sent-context keys are scoped per task: a global (unkeyed) store would prune context from the first
    // message of an unrelated task just because the same resource was sent from another one.
    it('records delivered non-text keys per task without leaking across tasks', async () => {
        const insight = { type: 'insight', key: 'x' }
        await expectLogic(logic, () => {
            logic.actions.contextDelivered('task-a', [insight, { type: 'text', value: 'note' }])
            logic.actions.contextDelivered('task-a', [insight, { type: 'dashboard', key: 9 }])
            logic.actions.contextDelivered('task-b', [insight])
        }).toMatchValues({
            sentContextKeysByTask: {
                'task-a': ['insight:x', 'dashboard:9'],
                'task-b': ['insight:x'],
            },
        })
    })

    it('saves references but no payload as chips, which outlive the provider and are removed per chat', async () => {
        const responses = 'private survey answer'
        const items = [
            { type: 'experiment', key: 17, label: 'Checkout' },
            { type: 'survey_open_ended_responses', value: responses, label: 'Open-ended responses' },
            { type: 'text', value: responses },
            { type: 'tool_context', value: responses, hidden: true },
            { type: 'email_template', key: 't1', label: 'Welcome', previewHtml: '<p>Hi</p>' },
            { type: 'text', key: 'note', value: responses },
        ]
        logic.actions.registerContext('scene', items)
        logic.actions.contextDelivered('task-a', items)
        logic.actions.contextDelivered('task-b', [items[0]])
        logic.actions.deregisterContext('scene')

        const chips = logic.values.chatChipsByTask['task-a']
        expect(chips.map((chip) => chip.label)).toEqual([
            'Checkout',
            'Open-ended responses',
            'Text',
            'Welcome',
            'text note',
        ])
        expect(JSON.stringify(chips)).not.toContain(responses)
        expect(JSON.stringify(chips)).not.toContain('<p>Hi</p>')

        logic.actions.removeChatChip('task-a', 'experiment:17')

        expect(logic.values.chatChipsByTask['task-a']).toHaveLength(4)
        expect(logic.values.chatChipsByTask['task-b']).toHaveLength(1)
    })

    it('evicts the chat with the oldest delivery once the persisted store is full', async () => {
        for (let chat = 0; chat <= 49; chat++) {
            logic.actions.contextDelivered(`bounded-${chat}`, [{ type: 'insight', key: 'x' }])
        }
        logic.actions.contextDelivered('bounded-0', [{ type: 'dashboard', key: 'y' }])
        logic.actions.contextDelivered('bounded-50', [{ type: 'insight', key: 'x' }])

        expect(logic.values.chatChipsByTask['bounded-0']).toHaveLength(2)
        expect(logic.values.chatChipsByTask['bounded-1']).toBeUndefined()
        expect(Object.keys(logic.values.chatChipsByTask)).toHaveLength(50)
    })

    it('dismissal hides an item, survives provider re-registration, and undismiss restores it', async () => {
        const item = { type: 'insight', key: 'x', label: 'X' }

        await expectLogic(logic, () => {
            logic.actions.registerContext('bridge', [item])
            logic.actions.dismissContext('insight:x')
        }).toMatchValues({ contextItems: [] })

        // A provider upsert (e.g. the scene bridge re-reading the scene) must not resurrect the chip.
        await expectLogic(logic, () => {
            logic.actions.registerContext('bridge', [item])
        }).toMatchValues({ contextItems: [] })

        await expectLogic(logic, () => {
            logic.actions.undismissContext('insight:x')
        }).toMatchValues({ contextItems: [item] })
    })

    // A chip's dismissal must extend to the hidden payload items registered alongside it, and must
    // survive re-registrations whose value (and therefore dedupe key) changed, as live editor state
    // does on every edit; key-based dismissal alone lets the payload resurrect on the next edit.
    it('dismissing with a dismissGroup hides the whole group, including re-registrations with new values', async () => {
        const groupItems = (stateValue: string): AttachedContextItem[] => [
            { type: 'hog_flow', key: '1', label: 'Flow', dismissGroup: 'g' },
            { type: 'hog_flow_editor_state', value: stateValue, hidden: true, dismissGroup: 'g' },
            { type: 'insight', key: 'other' },
        ]

        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', groupItems('v1'))
            logic.actions.dismissContext('hog_flow:1', 'g')
        }).toMatchValues({ contextItems: [{ type: 'insight', key: 'other' }] })

        await expectLogic(logic, () => {
            logic.actions.registerContext('scene', groupItems('v2'))
        }).toMatchValues({ contextItems: [{ type: 'insight', key: 'other' }] })

        await expectLogic(logic, () => {
            logic.actions.undismissContext('hog_flow:1', 'g')
        }).toMatchValues({ contextItems: groupItems('v2') })
    })
})
