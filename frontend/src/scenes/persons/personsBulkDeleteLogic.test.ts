import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { personsBulkDeleteLogic } from './personsBulkDeleteLogic'

describe('personsBulkDeleteLogic', () => {
    let logic: ReturnType<typeof personsBulkDeleteLogic.build>
    let requests: any[]
    let pages: { persons_deleted: number; has_more: boolean }[]
    let pageIndex: number

    const filters = {
        properties: [
            {
                type: PropertyFilterType.Person as const,
                key: '$os',
                value: 'Chrome',
                operator: PropertyOperator.Exact,
            },
        ],
    }

    const deleteRequests = (): any[] => requests.filter((body) => !body.dry_run)

    beforeEach(() => {
        requests = []
        pages = [{ persons_deleted: 1, has_more: false }]
        pageIndex = 0
        useMocks({
            post: {
                '/api/projects/:project_id/persons/bulk_delete/': async ({ request }) => {
                    const body: any = await request.clone().json()
                    requests.push(body)
                    if (body.dry_run) {
                        return [
                            200,
                            {
                                persons_found: pages.reduce((sum, page) => sum + page.persons_deleted, 0),
                                persons_deleted: 0,
                                has_more: false,
                                events_queued_for_deletion: false,
                                recordings_queued_for_deletion: false,
                                deletion_errors: [],
                            },
                        ]
                    }
                    const page = pages[Math.min(pageIndex, pages.length - 1)]
                    pageIndex += 1
                    return [
                        200,
                        {
                            persons_found: page.persons_deleted,
                            persons_deleted: page.persons_deleted,
                            has_more: page.has_more,
                            events_queued_for_deletion: false,
                            recordings_queued_for_deletion: false,
                            deletion_errors: [],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = personsBulkDeleteLogic()
        logic.mount()
    })

    it('counts the matching persons without deleting when the modal opens', async () => {
        pages = [{ persons_deleted: 7, has_more: false }]

        logic.actions.openModal(filters)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ matchCount: 7 })

        expect(requests).toEqual([expect.objectContaining({ dry_run: true })])
    })

    it('keeps deleting pages while the server reports more matches', async () => {
        pages = [
            { persons_deleted: 1000, has_more: true },
            { persons_deleted: 1000, has_more: true },
            { persons_deleted: 340, has_more: false },
        ]

        logic.actions.openModal(filters)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.deleteMatchingPersons()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ deletedCount: 2340, isDeleting: false })

        expect(deleteRequests()).toHaveLength(3)
    })

    it('gives up rather than looping forever when a page matches but deletes nothing', async () => {
        pages = [{ persons_deleted: 0, has_more: true }]

        logic.actions.openModal(filters)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.deleteMatchingPersons()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ deletedCount: 0 })

        expect(deleteRequests()).toHaveLength(3)
    })

    it('passes the delete_events and delete_recordings choices through', async () => {
        pages = [{ persons_deleted: 2, has_more: false }]

        logic.actions.openModal(filters)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDeleteEvents(true)
        logic.actions.setDeleteRecordings(true)
        logic.actions.deleteMatchingPersons()
        await expectLogic(logic).toFinishAllListeners()

        expect(deleteRequests()).toEqual([expect.objectContaining({ delete_events: true, delete_recordings: true })])
    })
})
