import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import { query } from '~/queries/query'

import type { hogQLEditorLogicType } from './hogQLEditorLogicType'
import { HogQLMetadata, HogQLMetadataResponse, NodeKind } from '~/queries/schema'
import { loaders } from 'kea-loaders'

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
        submit: true,
    }),
    loaders(({ props, values }) => ({
        response: [
            null as HogQLMetadataResponse | null,
            {
                submit: async (_, breakpoint) => {
                    if (!values.localValue) {
                        return null
                    }
                    const response = await query<HogQLMetadata>({
                        kind: NodeKind.HogQLMetadata,
                        expr: values.localValue,
                    })
                    breakpoint()
                    if (response && !response?.error) {
                        props.onChange(values.localValue)
                    }
                    return response ?? null
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        localValue: [props.value ?? '', { setLocalValue: (_, { localValue }) => localValue }],
        response: { setLocalValue: () => null },
    })),
    selectors({
        error: [(s) => [s.response], (response) => response?.error ?? null],
    }),
    propsChanged(({ props, actions }, oldProps) => {
        if (props.value !== oldProps.value) {
            actions.setLocalValue(props.value ?? '')
        }
    }),
])
