import { render } from '@testing-library/react'

import { ActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { replayActivityDescriber } from './activityDescription'

describe('replay activity descriptions', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('shows a recording export with its destination, role and approver', () => {
        // The shape record_export in export_recordings_to_s3.py writes.
        const logItem: ActivityLogItem = {
            user: undefined,
            is_system: true,
            activity: 'exported',
            created_at: '2026-11-23T00:00:00Z',
            scope: ActivityScope.REPLAY,
            item_id: 'q1',
            detail: {
                merge: null,
                name: 'Recordings exported to s3://customer/exports',
                changes: null,
                trigger: {
                    job_type: 'export_recordings_to_s3',
                    job_id: 'export-recordings-1-q1',
                    payload: {
                        role_arn: 'arn:aws:iam::123456789012:role/r',
                        bucket: 'customer',
                        prefix: 'exports',
                        approved_by: 'approver@example.com',
                    },
                },
            },
        }

        const [humanized] = humanize([logItem], () => replayActivityDescriber)
        const { container } = render(<>{humanized.description}</>)

        expect(container.textContent).toBe(
            'PostHog exported session recordings to s3://customer/exports as role arn:aws:iam::123456789012:role/r, approved by approver@example.com'
        )
    })
})
