import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { ConditionalFormattingRule } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { FORMATTING_TEMPLATES, FormattingTemplate } from '../../types'
import type { conditionalFormattingLogicType } from './conditionalFormattingLogicType'

export interface ConditionalFormattingLogicProps {
    rule: ConditionalFormattingRule
    key: string
}

export const conditionalFormattingLogic = kea<conditionalFormattingLogicType>([
    key((props) => props.rule.id),
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'conditionalFormattingLogic']),
    props({ rule: { id: '' }, key: '' } as ConditionalFormattingLogicProps),
    connect(() => ({
        actions: [dataVisualizationLogic, ['updateConditionalFormattingRule']],
    })),
    actions({
        selectColumn: (columnName: string) => ({ columnName }),
        updateInput: (input: string) => ({ input }),
        selectTemplate: (templateId: string) => ({ templateId }),
        updateBytecode: (bytecode: any[]) => ({ bytecode }),
        selectColor: (color: string) => ({ color }),
        deleteRule: true,
    }),
    reducers(({ props }) => ({
        rule: [
            props.rule,
            {
                selectColumn: (state, { columnName }) => {
                    return { ...state, columnName }
                },
                updateInput: (state, { input }) => {
                    return { ...state, input }
                },
                selectTemplate: (state, { templateId }) => {
                    return { ...state, templateId }
                },
                updateBytecode: (state, { bytecode }) => {
                    return { ...state, bytecode }
                },
                selectColor: (state, { color }) => {
                    return { ...state, color }
                },
            },
        ],
    })),
    selectors({
        template: [
            (s) => [s.rule],
            (rule): FormattingTemplate => {
                const template = FORMATTING_TEMPLATES.find((n) => n.id === rule.templateId)
                if (!template) {
                    return FORMATTING_TEMPLATES[0]
                }

                return template
            },
        ],
    }),
    loaders({
        hog: [
            null as null | any[],
            {
                compileHog: async ({ hog }) => {
                    const res = await api.hog.create(hog)
                    return res.bytecode
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        compileHogSuccess: ({ hog }) => {
            actions.updateBytecode(hog)
        },
        deleteRule: () => {
            actions.updateConditionalFormattingRule(values.rule, true)
        },
    })),
    subscriptions(({ actions }) => ({
        template: (template: FormattingTemplate, oldTemplate: FormattingTemplate | undefined) => {
            actions.compileHog({ hog: template.hog })

            // If we've changed to a template with a disabled `input` field, then clear the input
            if (!oldTemplate?.hideInput && template.hideInput) {
                actions.updateInput('')
            }
        },
        rule: (rule: ConditionalFormattingRule) => {
            actions.updateConditionalFormattingRule(rule)
        },
    })),
])
