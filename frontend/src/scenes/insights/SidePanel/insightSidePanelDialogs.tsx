import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { AnyDataNode, NodeKind } from '~/queries/schema/schema-general'

const RESOURCE_TYPE = 'insight'

export function openSaveAsCohortDialog(
    createStaticCohort: (name: string, query: AnyDataNode) => void,
    hogQL: string,
    hogQLVariables?: Record<string, any>
): void {
    LemonDialog.openForm({
        title: 'Save as static cohort',
        description: (
            <div className="mt-2">
                Your query must export a <code>person_id</code>, <code>actor_id</code>, <code>id</code>, or{' '}
                <code>distinct_id</code> column. The <code>person_id</code>, <code>actor_id</code>, and <code>id</code>{' '}
                columns must match the <code>id</code> of the <code>persons</code> table, while <code>distinct_id</code>{' '}
                will be automatically resolved to the corresponding person.
            </div>
        ),
        initialValues: { name: '' },
        content: (
            <LemonField name="name">
                <LemonInput
                    data-attr={`${RESOURCE_TYPE}-save-as-cohort-name`}
                    placeholder="Name of the new cohort"
                    autoFocus
                />
            </LemonField>
        ),
        errors: { name: (name) => (!name ? 'You must enter a name' : undefined) },
        onSubmit: async ({ name }) => {
            createStaticCohort(name, { kind: NodeKind.HogQLQuery, query: hogQL, variables: hogQLVariables })
        },
    })
}
