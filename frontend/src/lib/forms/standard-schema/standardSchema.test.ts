import { z } from 'zod'

import { parseWithStandardSchema, standardSchemaToKeaErrors } from './standardSchema'

describe('standardSchema adapter', () => {
    const schema = z.object({
        repository: z.object({
            fullName: z.string().trim().min(1, 'Repository name is required'),
            baselinePaths: z.record(
                z.string().trim().min(1, 'Run type is required'),
                z.string().trim().min(1, 'Path is required')
            ),
        }),
        entries: z.array(
            z.object({
                name: z.string().trim().min(1, 'Name is required'),
            })
        ),
    })

    it('maps nested object and array paths into kea errors', () => {
        const errors = standardSchemaToKeaErrors(schema, {
            repository: {
                fullName: '',
                baselinePaths: {
                    storybook: '',
                },
            },
            entries: [{ name: '' }],
        })

        expect(errors).toEqual({
            repository: {
                fullName: 'Repository name is required',
                baselinePaths: {
                    storybook: 'Path is required',
                },
            },
            entries: {
                0: {
                    name: 'Name is required',
                },
            },
        })
    })

    it('returns parsed values on success', () => {
        const parsed = parseWithStandardSchema(schema, {
            repository: {
                fullName: ' posthog/posthog ',
                baselinePaths: {
                    storybook: ' .storybook/snapshots.yml ',
                },
            },
            entries: [{ name: ' smoke ' }],
        })

        expect(parsed).toEqual({
            success: true,
            data: {
                repository: {
                    fullName: 'posthog/posthog',
                    baselinePaths: {
                        storybook: '.storybook/snapshots.yml',
                    },
                },
                entries: [{ name: 'smoke' }],
            },
        })
    })
})
