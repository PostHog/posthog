import { IconApps, IconChat, IconLock, IconLogomark, IconNotebook, IconPulse } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { SidePanelTab } from '~/types'

import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { SidePanelActivityIcon } from './panels/activity/SidePanelActivityIcon'
import { SidePanelDiscussionIcon } from './panels/discussion/SidePanelDiscussionIcon'
import { SidePanelExportsIcon } from './panels/exports/SidePanelExportsIcon'
import { SidePanelInfo, SidePanelInfoIcon } from './panels/info/SidePanelInfo'

const SidePanelMax = lazyWithRetry(() => import('./panels/max/SidePanelMax').then((m) => ({ default: m.SidePanelMax })))
const NotebookPanel = lazyWithRetry(() =>
    import('scenes/notebooks/NotebookPanel/NotebookPanel').then((m) => ({ default: m.NotebookPanel }))
)
// The support panel renders the ticket editor, which pulls in tiptap extensions and lowlight.
const SidePanelSupport = lazyWithRetry(() =>
    import('./panels/support/SidePanelSupport').then((m) => ({ default: m.SidePanelSupport }))
)
// Discussion renders the comment composer, which pulls in the rich content editor and emoji picker.
const SidePanelDiscussion = lazyWithRetry(() =>
    import('./panels/discussion/SidePanelDiscussion').then((m) => ({ default: m.SidePanelDiscussion }))
)
const SidePanelAccessControl = lazyWithRetry(() =>
    import('./panels/access_control/SidePanelAccessControl').then((m) => ({ default: m.SidePanelAccessControl }))
)
const SidePanelAccessDetail = lazyWithRetry(() =>
    import('./panels/access_control/SidePanelAccessDetail').then((m) => ({ default: m.SidePanelAccessDetail }))
)
const SidePanelExports = lazyWithRetry(() =>
    import('./panels/exports/SidePanelExports').then((m) => ({ default: m.SidePanelExports }))
)
const CanvasSidePanel = lazyWithRetry(() =>
    import('products/canvas/frontend/sidePanel/CanvasSidePanel').then((m) => ({ default: m.CanvasSidePanel }))
)
const SidePanelActivity = lazyWithRetry(() =>
    import('./panels/activity/SidePanelActivity').then((m) => ({ default: m.SidePanelActivity }))
)

export const SIDE_PANEL_TABS: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Max]: {
        label: 'PostHog AI',
        Icon: IconLogomark,
        Content: SidePanelMax,
    },
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: NotebookPanel,
    },
    [SidePanelTab.Support]: {
        label: 'Support',
        Icon: SidePanelSupportIcon,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Exports]: {
        label: 'Exports',
        Icon: SidePanelExportsIcon,
        Content: SidePanelExports,
    },
    [SidePanelTab.Activity]: {
        label: 'Activity logs',
        Icon: SidePanelActivityIcon,
        Content: SidePanelActivity,
    },
    [SidePanelTab.Discussion]: {
        label: 'Discuss',
        Icon: SidePanelDiscussionIcon,
        Content: SidePanelDiscussion,
    },
    [SidePanelTab.AccessControl]: {
        label: 'Access',
        Icon: IconLock,
        Content: SidePanelAccessControl,
    },
    [SidePanelTab.AccessDetail]: {
        label: 'Access',
        Icon: IconLock,
        Content: SidePanelAccessDetail,
    },
    [SidePanelTab.Info]: {
        label: 'Actions',
        Icon: SidePanelInfoIcon,
        Content: SidePanelInfo,
    },
    [SidePanelTab.CanvasChat]: {
        label: 'Chat',
        Icon: IconChat,
        Content: CanvasSidePanel,
    },
    [SidePanelTab.CanvasBlocks]: {
        label: 'Blocks',
        Icon: IconApps,
        Content: CanvasSidePanel,
    },
    [SidePanelTab.CanvasTimeline]: {
        label: 'Timeline',
        Icon: IconPulse,
        Content: CanvasSidePanel,
    },
}
