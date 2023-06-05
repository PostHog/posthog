import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { query } from '~/queries/query'

import type { hogQLEditorLogicType } from './hogQLEditorLogicType'
import { HogQLMetadataResponse, NodeKind } from '~/queries/schema'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

export interface HogQLEditorLogicProps {
    key: string
    value: string | undefined
    onChange: (value: string) => void
}

export const hogQLEditorLogic = kea<hogQLEditorLogicType>([
    path(['lib', 'components', 'HogQLEditor', 'hogQLEditorLogic']),
    props({} as HogQLEditorLogicProps),
    key((props) => props.key),
    actions({
        setLocalValue: (localValue: string) => ({ localValue }),
        setError: (error: string | null) => ({ error }),
        submit: true,
        validate: true,
    }),
    reducers(({ props }) => ({
        localValue: [props.value ?? '', { setLocalValue: (_, { localValue }) => localValue }],
        error: [null as string | null, { setError: (_, { error }) => error, setLocalValue: () => null }],
    })),
    propsChanged(({ props, actions }, oldProps) => {
        if (props.value !== oldProps.value) {
            actions.setLocalValue(props.value ?? '')
        }
    }),
    listeners(({ actions, props, values }) => ({
        setLocalValue: async (_, breakpoint) => {
            await breakpoint(300)
            actions.validate()
        },
        validate: async (_, breakpoint) => {
            try {
                if (!values.localValue) {
                    return
                }
                const response = await query({
                    kind: NodeKind.HogQLMetadata,
                    expr: values.localValue,
                })
                breakpoint()
                const error = (response as HogQLMetadataResponse).error ?? null
                if (error !== values.error) {
                    actions.setError(error)
                }
            } catch (e) {
                lemonToast.error(`Error validating query: ${e}`)
            }
        },
        submit: () => {
            props.onChange(values.localValue)
        },
    })),
])
