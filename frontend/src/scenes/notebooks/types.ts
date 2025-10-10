import { Attribute, ExtendedRegExpMatchArray } from '@tiptap/core'

import { LemonButtonProps } from '@posthog/lemon-ui'

import {
    JSONContent,
    RichContentEditorType,
    RichContentNode,
    RichContentNodeType,
} from 'lib/components/RichContentEditor/types'

import { UserBasicType, WithAccessControl } from '~/types'

import type { NotebookNodeLogicProps } from './Nodes/notebookNodeLogic'

export type { TableOfContentData } from '@tiptap/extension-table-of-contents'

export type NotebookListItemType = {
    id: string
    short_id: string
    title?: string
    is_template?: boolean
    created_at: string
    created_by: UserBasicType | null
    last_modified_at?: string
    last_modified_by?: UserBasicType | null
    _create_in_folder?: string
}

export type NotebookType = NotebookListItemType &
    WithAccessControl & {
        content: JSONContent | null
        version: number
        // used to power text-based search
        text_content?: string | null
    }

export enum NotebookNodeType {
    Mention = RichContentNodeType.Mention,
    Query = 'ph-query',
    Recording = 'ph-recording',
    RecordingPlaylist = 'ph-recording-playlist',
    FeatureFlag = 'ph-feature-flag',
    FeatureFlagCodeExample = 'ph-feature-flag-code-example',
    Experiment = 'ph-experiment',
    EarlyAccessFeature = 'ph-early-access-feature',
    Survey = 'ph-survey',
    Person = 'ph-person',
    Group = 'ph-group',
    Cohort = 'ph-cohort',
    Backlink = 'ph-backlink',
    ReplayTimestamp = 'ph-replay-timestamp',
    Image = 'ph-image',
    PersonFeed = 'ph-person-feed',
    Properties = 'ph-properties',
    Map = 'ph-map',
    Embed = 'ph-embed',
    Latex = 'ph-latex',
    TaskCreate = 'ph-task-create',
    LLMTrace = 'ph-llm-trace',
}

export type NotebookNodeResource = {
    attrs: Record<string, any>
    type: NotebookNodeType
}

export enum NotebookTarget {
    Popover = 'popover',
    Scene = 'scene',
}

export type NotebookSyncStatus = 'synced' | 'saving' | 'unsaved' | 'local'

export type NotebookPopoverVisibility = 'hidden' | 'visible' | 'peek'

export type CustomNotebookNodeAttributes = Record<string, any>

export type CreatePostHogWidgetNodeOptions<T extends CustomNotebookNodeAttributes> = Omit<
    NodeWrapperProps<T>,
    'updateAttributes'
> & {
    Component: (props: NotebookNodeProps<T>) => JSX.Element | null
    pasteOptions?: {
        find: string | RegExp
        getAttributes: (match: ExtendedRegExpMatchArray) => Promise<T | null | undefined> | T | null | undefined
    }
    inputOptions?: {
        find: string | RegExp
        getAttributes: (match: ExtendedRegExpMatchArray) => Promise<T | null | undefined> | T | null | undefined
    }
    attributes: Record<keyof T, Partial<Attribute>>
    serializedText?: (attributes: NotebookNodeAttributes<T>) => string
}

export type NodeWrapperProps<T extends CustomNotebookNodeAttributes> = Omit<NotebookNodeLogicProps, 'notebookLogic'> &
    NotebookNodeProps<T> & {
        Component: (props: NotebookNodeProps<T>) => JSX.Element | null

        // View only props
        href?: string | ((attributes: NotebookNodeAttributes<T>) => string | undefined)
        expandable?: boolean
        selected?: boolean
        heightEstimate?: number | string
        minHeight?: number | string
        /** If true the metadata area will only show when hovered if in editing mode */
        autoHideMetadata?: boolean
        /** Expand the node if the component is clicked */
        expandOnClick?: boolean
        settingsIcon?: JSX.Element | 'filter' | 'gear'
    }

export type NotebookNodeAttributes<T extends CustomNotebookNodeAttributes> = T & {
    nodeId: string
    height?: string | number
    title?: string
    __init?: {
        expanded?: boolean
        showSettings?: boolean
    }
    // TODO: Type this more specifically to be our supported nodes only
    children?: NotebookNodeResource[]
}

// NOTE: Pushes users to use the parsed "attributes" instead
export type NotebookNode = Omit<RichContentNode, 'attrs'>

export type NotebookNodeAttributeProperties<T extends CustomNotebookNodeAttributes> = {
    attributes: NotebookNodeAttributes<T>
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<T>>) => void
}

export type NotebookNodeProps<T extends CustomNotebookNodeAttributes> = NotebookNodeAttributeProperties<T>

export type NotebookNodeSettings =
    // using 'any' here shouldn't be necessary but, I couldn't figure out how to set a generic on the notebookNodeLogic props
    (({ attributes, updateAttributes }: NotebookNodeAttributeProperties<any>) => JSX.Element) | null

export type NotebookNodeAction = Pick<LemonButtonProps, 'icon'> & {
    text: string
    onClick: () => void
}

export interface NotebookEditor extends RichContentEditorType {
    findCommentPosition: (markId: string) => number | null
    removeComment: (pos: number) => void
    getText: () => string
}

declare module '@tiptap/core' {
    interface NodeConfig {
        // TODO: Not a big fan of any here but it's ok for now
        // the Node type should probably not be augmented with a new method as we are
        // instead we should probably make a new extension type that does what we want
        // or have some kind of wrapper around the existing Node
        serializedText: (attrs: NotebookNodeAttributes<any>) => string
    }
}
