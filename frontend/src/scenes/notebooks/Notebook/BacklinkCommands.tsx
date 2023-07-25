import { Extension } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'

import { Popover } from 'lib/lemon-ui/Popover'
import { forwardRef } from 'react'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { EditorRange } from './utils'
import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { NotebookNodeType } from '~/types'

type BacklinkCommandsProps = {
    query?: string
    range?: EditorRange
    onClose: () => void
    decorationNode?: any
}

const BacklinkCommandsPopover = forwardRef<ReactRenderer, BacklinkCommandsProps>(function BacklinkCommandsPopover(
    props: BacklinkCommandsProps,
    ref
): JSX.Element | null {
    return (
        <Popover overlay={<BacklinkCommands ref={ref} {...props} />} visible referenceElement={props.decorationNode} />
    )
})

const BacklinkCommands = forwardRef<ReactRenderer, BacklinkCommandsProps>(function BacklinkCommands({
    range = { from: 0, to: 0 },
    query,
    onClose,
}): JSX.Element | null {
    // TODO: Use ref, otherwise React complaints
    const { editor } = useValues(notebookLogic)

    const onSelect = (
        { type }: TaxonomicFilterGroup,
        value: TaxonomicFilterValue,
        { id, name }: { id: number; name: string }
    ): void => {
        if (!editor) {
            return
        }

        const attrs = {
            id: type === TaxonomicFilterGroupType.Events ? id : value,
            title: name,
            type: type,
        }

        editor
            .deleteRange(range)
            .insertContentAt(range, [
                { type: NotebookNodeType.Backlink, attrs },
                { type: 'text', text: ' ' },
            ])
            .run()
    }

    if (!editor) {
        return null
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.Events,
        value: query,
        onChange: onSelect,
        onClose: onClose,
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Persons,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.Insights,
            TaxonomicFilterGroupType.FeatureFlags,
            TaxonomicFilterGroupType.Experiments,
            TaxonomicFilterGroupType.Dashboards,
        ],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'notebook',
    }

    return <TaxonomicFilter {...taxonomicFilterLogicProps} />
})

const BacklinkCommandsPluginKey = new PluginKey('backlink-commands')

export const BacklinkCommandsExtension = Extension.create({
    name: 'backlink-commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                pluginKey: BacklinkCommandsPluginKey,
                editor: this.editor,
                char: '@',
                allow: ({ range }) => range.to - range.from === 1,
                render: () => {
                    let renderer: ReactRenderer

                    const onClose = (): void => {
                        renderer.destroy()
                        this.editor.chain().focus().run()
                    }

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(BacklinkCommandsPopover, {
                                props: { ...props, onClose },
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps(props)

                            if (!props.clientRect) {
                                return
                            }
                        },

                        onExit() {
                            onClose()
                        },
                    }
                },
            }),
        ]
    },
})
