import { IconInfo } from '@posthog/icons'

import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'

import { AnyDataNode, Node, NodeKind } from '~/queries/schema/schema-general'

const RESOURCE_TYPE = 'insight'

export function openShareTemplateDialog(query: Node | null, siteUrl: string): void {
    const templateLink = getInsightDefinitionUrl({ query }, siteUrl)
    LemonDialog.open({
        title: (
            <span className="flex items-center gap-2">
                <TitleWithIcon
                    icon={
                        <Tooltip title={TEMPLATE_LINK_TOOLTIP}>
                            <IconInfo />
                        </Tooltip>
                    }
                >
                    <b>{TEMPLATE_LINK_HEADING}</b>
                </TitleWithIcon>
            </span>
        ),
        content: (
            <TemplateLinkSection
                templateLink={templateLink}
                heading={undefined}
                piiWarning={TEMPLATE_LINK_PII_WARNING}
            />
        ),
        width: 600,
        primaryButton: { children: 'Close', type: 'secondary' },
    })
}

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
