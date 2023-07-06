import { Extension } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'

import { Popover } from 'lib/lemon-ui/Popover'
import { forwardRef } from 'react'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { EditorRange } from './utils'
import { useValues } from 'kea'
import { notebookLogic } from './notebookLogic'

type BacklinkCommandsProps = {
    query?: string
    range?: EditorRange
    decorationNode?: any
}

type BacklinkCommandsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

const BacklinkCommandsPopover = forwardRef<BacklinkCommandsRef, BacklinkCommandsProps>(function BacklinkCommandsPopover(
    props: BacklinkCommandsProps,
    ref
): JSX.Element | null {
    return (
        <Popover overlay={<BacklinkCommands ref={ref} {...props} />} visible referenceElement={props.decorationNode} />
    )
})

const BacklinkCommands = forwardRef<BacklinkCommandsRef, BacklinkCommandsProps>(function BacklinkCommands({
    range = { from: 0, to: 0 },
    query,
}): JSX.Element | null {
    const { editor } = useValues(notebookLogic)

    const onPressEnter = (): void => {
        if (!editor) {
            return
        }

        editor
            .deleteRange(range)
            .insertContentAt(range, [
                { type: 'text', marks: [{ type: 'underline' }], text: ' ' },
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
        onChange: onPressEnter,
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Persons,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.Insights,
            TaxonomicFilterGroupType.FeatureFlags,
            TaxonomicFilterGroupType.Plugins,
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
                char: '#',
                render: () => {
                    let renderer: ReactRenderer<BacklinkCommandsRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(BacklinkCommandsPopover, {
                                props,
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps(props)

                            if (!props.clientRect) {
                                return
                            }
                        },

                        onKeyDown(props) {
                            if (props.event.key === 'Escape') {
                                renderer.destroy()
                                return true
                            }
                            return renderer.ref?.onKeyDown(props.event) ?? false
                        },

                        onExit() {
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
