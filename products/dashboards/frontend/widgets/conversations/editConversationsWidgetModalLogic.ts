import { MakeLogicType, actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { ConversationsRecentTicketsWidgetConfig } from '../../generated/widget-configs.zod'
import { conversationsRecentTicketsWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
    widgetEditModalTileActions,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'

export type EditConversationsWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export interface editConversationsWidgetModalLogicValues {
    config: ConversationsRecentTicketsWidgetConfig
    defaultTitle: string
    limit: number
    onClose: () => void
    saving: boolean
    tileDescription: string
    tileName: string
}

export interface editConversationsWidgetModalLogicActions {
    setLimit: (limit: number) => { limit: number }
    setTileDescription: (tileDescription: string) => { tileDescription: string }
    setTileName: (tileName: string) => { tileName: string }
    submit: () => { value: true }
    submitFailure: () => { value: true }
    submitSuccess: () => { value: true }
}

export type editConversationsWidgetModalLogicType = MakeLogicType<
    editConversationsWidgetModalLogicValues,
    editConversationsWidgetModalLogicActions,
    EditConversationsWidgetModalLogicProps
>

export const editConversationsWidgetModalLogic = kea<editConversationsWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'conversations', 'editConversationsWidgetModalLogic']),
    props({} as EditConversationsWidgetModalLogicProps),
    actions({
        ...widgetEditModalTileActions,
        setLimit: (limit: number) => ({ limit }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),
    reducers({
        limit: [10, { setLimit: (_state: number, { limit }: { limit: number }) => limit }],
        tileName: ['', { setTileName: (_state: string, { tileName }: { tileName: string }) => tileName }],
        tileDescription: [
            '',
            {
                setTileDescription: (_state: string, { tileDescription }: { tileDescription: string }) =>
                    tileDescription,
            },
        ],
        saving: [false, { submit: () => true, submitSuccess: () => false, submitFailure: () => false }],
        defaultTitle: ['Recent tickets'],
    }),
    selectors({
        config: [
            (_state, props) => [props.config],
            (config): ConversationsRecentTicketsWidgetConfig =>
                conversationsRecentTicketsWidgetConfigSchema.parse(config),
        ],
        onClose: [(_state, props) => [props.onClose], (onClose): (() => void) => onClose],
    }),
    listeners(({ actions, values, props }) => ({
        submit: async () => {
            try {
                const config = conversationsRecentTicketsWidgetConfigSchema.parse({
                    ...values.config,
                    limit: values.limit,
                })
                await props.onSave(config, buildWidgetTileMetadataPatch(props, values.tileName, values.tileDescription))
                actions.submitSuccess()
                props.onClose()
            } catch {
                actions.submitFailure()
                lemonToast.error('Could not save widget settings. Check your connection and try again.')
            }
        },
    })),
    afterMount(({ actions, props }) => {
        const config = conversationsRecentTicketsWidgetConfigSchema.parse(props.config)
        const metadata = getWidgetEditModalTileDefaults(props)
        actions.setLimit(config.limit ?? 10)
        actions.setTileName(metadata.tileName)
        actions.setTileDescription(metadata.tileDescription)
    }),
])
