import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { AnyDataNode, HogQLFilters, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

const RESOURCE_TYPE = 'insight'

export function openSaveAsCohortDialog(
    createStaticCohort: (name: string, query: AnyDataNode) => void,
    hogQL: string,
    hogQLVariables?: Record<string, any>,
    hogQLFilters?: HogQLFilters,
    hogQLValues?: HogQLQuery['values']
): void {
    LemonDialog.openForm({
        title: 'Save as static cohort',
        description: (
            <p>
                Return person IDs in a <code>person_id</code>, <code>actor_id</code>, or <code>id</code> column, or use{' '}
                <code>distinct_id</code> to look up the matching people.
            </p>
        ),
        initialValues: { name: '' },
        content: (
            <LemonField name="name" label="Name">
                <LemonInput
                    data-attr={`${RESOURCE_TYPE}-save-as-cohort-name`}
                    placeholder="Name of the new cohort"
                    autoFocus
                />
            </LemonField>
        ),
        errors: { name: (name) => (!name ? 'You must enter a name' : undefined) },
        onSubmit: async ({ name }) => {
            createStaticCohort(name, {
                kind: NodeKind.HogQLQuery,
                query: hogQL,
                variables: hogQLVariables,
                filters: hogQLFilters,
                values: hogQLValues,
            })
        },
    })
}
