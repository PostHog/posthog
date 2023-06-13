import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import { query } from '~/queries/query'

import type { hogQLEditorLogicType } from './hogQLEditorLogicType'
import { HogQLMetadata, HogQLMetadataResponse, NodeKind } from '~/queries/schema'
import { loaders } from 'kea-loaders'
import React from 'react'

export interface HogQLEditorLogicProps {
    key: string
    value: string | undefined
    onChange: (value: string) => void
    textareaRef?: React.MutableRefObject<HTMLTextAreaElement | null>
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
                    if (response?.error) {
                        const textArea = props.textareaRef?.current
                        if (
                            textArea &&
                            typeof response.errorStart === 'number' &&
                            typeof response.errorEnd === 'number'
                        ) {
                            textArea.focus()
                            textArea.selectionStart = response.errorStart
                            textArea.selectionEnd = response.errorEnd
                        }
                    } else if (response) {
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
        error: [
            (s) => [s.response],
            (response) => {
                let error = response?.error ?? null
                if (error && response?.inputExpr && typeof response?.errorStart === 'number') {
                    let row = 0
                    let col = 0
                    for (let pos = 0; pos < response.errorStart; pos++) {
                        if (response.inputExpr[pos] === '\n') {
                            row += 1
                            col = 0
                        } else {
                            col += 1
                        }
                    }
                    error = `Line ${row + 1}, column ${col + 1}: ${error}`
                }

                return error
            },
        ],
    }),
    propsChanged(({ props, actions }, oldProps) => {
        if (props.value !== oldProps.value) {
            actions.setLocalValue(props.value ?? '')
        }
    }),
])
