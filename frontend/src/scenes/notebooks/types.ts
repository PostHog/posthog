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
    Python = 'ph-python',
    DuckSQL = 'ph-duck-sql',
    HogQLSQL = 'ph-hogql-sql',
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
    PersonProperties = 'ph-person-properties',
    GroupProperties = 'ph-group-properties',
    Map = 'ph-map',
    Embed = 'ph-embed',
    Latex = 'ph-latex',
    TaskCreate = 'ph-task-create',
    LLMTrace = 'ph-llm-trace',
    Issues = 'ph-issues',
    UsageMetrics = 'ph-usage-metrics',
    ZendeskTickets = 'ph-zendesk-tickets',
    RelatedGroups = 'ph-related-groups',
}

export interface CustomNotebookNodeAttributes {
    [key: string]: unknown
}

export type NotebookNodeResource = {
    attrs: CustomNotebookNodeAttributes
    type: NotebookNodeType
}

export type NotebookNodeSettingsPlacement = 'inline' | 'left'

export enum NotebookTarget {
    Popover = 'popover',
    Scene = 'scene',
}

export type NotebookSyncStatus = 'synced' | 'saving' | 'unsaved' | 'local'

export type NotebookPopoverVisibility = 'hidden' | 'visible' | 'peek'

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
        settingsPlacement?: NotebookNodeSettingsPlacement
    }

export type NotebookNodeAttributes<T extends CustomNotebookNodeAttributes> = T & {
    nodeId: string
    height?: string | number
    title?: string
    __init?: {
        expanded?: boolean
        showSettings?: boolean
    }
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
    | (({ attributes, updateAttributes }: NotebookNodeAttributeProperties<CustomNotebookNodeAttributes>) => JSX.Element)
    | null

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
        serializedText: (attrs: NotebookNodeAttributes<CustomNotebookNodeAttributes>) => string
    }
}
