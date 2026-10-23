import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccessResolutionPreview } from './AccessResolutionPreview'
import { ResolutionChange, ResolutionPreviewResponse } from './resolutionPreviewLogic'

describe('AccessResolutionPreview', () => {
    afterEach(cleanup)

    it.each([MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_TEAM.id + 1])(
        'links to the project that owns each rule (project %s)',
        async (projectId) => {
            const baseChange: ResolutionChange = {
                project_id: projectId,
                project_name: 'Example project',
                scope: 'object',
                resource: 'feature_flag',
                object_id: '123',
                object_name: 'Example flag',
                object_short_id: null,
                subject: { type: 'default', id: null, name: 'Everyone' },
                current: {
                    access_level: 'editor',
                    source: 'resource_default',
                    source_subject: null,
                    subject_name: null,
                },
                proposed: {
                    access_level: 'viewer',
                    source: 'object_default',
                    source_subject: null,
                    subject_name: null,
                },
                direction: 'loses',
            }
            const preview: ResolutionPreviewResponse = {
                changes: [
                    baseChange,
                    { ...baseChange, resource: 'dashboard', object_id: '456', object_name: 'Example dashboard' },
                    {
                        ...baseChange,
                        resource: 'insight',
                        object_id: '789',
                        object_name: 'Example insight',
                        object_short_id: 'abc123',
                    },
                    { ...baseChange, scope: 'resource', object_id: null, object_name: null },
                ],
                summary: { total: 4, gains: 0, loses: 4, resources: 1, objects: 3 },
            }
            useMocks({ get: { '/api/projects/:id/access_control_resolution_preview': preview } })
            initKeaTests()

            const { container } = render(<AccessResolutionPreview />)

            expect((await screen.findByText('Example flag')).closest('a')).toHaveAttribute(
                'href',
                `/project/${projectId}/feature-flags/123`
            )
            expect(screen.getByText('Example dashboard').closest('a')).toHaveAttribute(
                'href',
                `/project/${projectId}/dashboard/456`
            )
            expect(screen.getByText('Example insight').closest('a')).toHaveAttribute(
                'href',
                `/project/${projectId}/insights/abc123`
            )
            expect(
                Array.from(container.querySelectorAll('[data-attr="access-resolution-open-object"]')).map((link) =>
                    link.getAttribute('href')
                )
            ).toEqual([
                `/project/${projectId}/dashboard/456`,
                `/project/${projectId}/feature-flags/123`,
                `/project/${projectId}/insights/abc123`,
            ])
            expect(container.querySelector('[data-attr="access-resolution-edit-resource"]')).toHaveAttribute(
                'href',
                `/project/${projectId}/settings/environment-access-control`
            )
        }
    )
})
