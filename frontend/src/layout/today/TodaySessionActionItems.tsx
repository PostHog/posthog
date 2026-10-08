import { useActions, useValues } from 'kea'

import {
    IconArchive,
    IconCheckbox,
    IconCopy,
    IconExternal,
    IconFolder,
    IconPencil,
    IconPin,
    IconPinFilled,
    IconSearch,
    IconSend,
    IconStopFilled,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isMac } from 'lib/utils/dom'

import { TodayMenuParts } from './todayMenuParts'
import { todayArchiveShortcutLabel } from './todaySessionArchiveShortcut'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todayShellLogic } from './todayShellLogic'
import { TodaySpaceFileList } from './TodaySpaceFileList'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodaySessionMenuTarget } from './todayWorkItems'

interface TodaySessionActionItemsProps {
    parts: TodayMenuParts
    target: TodaySessionMenuTarget
    surface: TodaySessionSurface
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}

/** A session's actions, in Desktop's order: the edits, the places it can go, then archive last. */
export function TodaySessionActionItems({
    parts: { Item, Separator, Shortcut, Sub },
    target,
    surface,
    dataAttrPrefix,
}: TodaySessionActionItemsProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { spaces } = useValues(todaySpacesLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { toggleSessionSelection } = useActions(todaySessionSelectionLogic)
    const {
        setSessionPinned,
        startRenaming,
        requestArchive,
        moveSession,
        openHandoff,
        analyzeSession,
        openSessionInNewTab,
        copySessionLink,
        stopSession,
    } = useActions(todaySessionMenuLogic)
    const { menuId, sessionId, pinned, activeRunId } = target
    const runId = featureFlags[FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS] ? target.analysisRunId : null
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            {!phoneLayout && (
                <Item onClick={() => openSessionInNewTab(sessionId)} dataAttr={attr('open-new-tab')}>
                    <IconExternal />
                    Open in new tab
                </Item>
            )}
            <Item onClick={() => copySessionLink(sessionId)} dataAttr={attr('copy-link')}>
                <IconCopy />
                Copy link
            </Item>
            <Item onClick={() => setSessionPinned(sessionId, !pinned)} dataAttr={attr('pin')}>
                {pinned ? <IconPinFilled /> : <IconPin />}
                {pinned ? 'Unpin' : 'Pin'}
            </Item>
            <Item onClick={() => startRenaming(sessionId, surface)} dataAttr={attr('rename')}>
                <IconPencil />
                Rename…
            </Item>
            {runId && (
                <Item onClick={() => analyzeSession(sessionId, runId)} dataAttr={attr('analyze')}>
                    <IconSearch />
                    Run analysis
                </Item>
            )}
            {activeRunId && (
                <Item onClick={() => stopSession(sessionId, activeRunId)} dataAttr={attr('stop')}>
                    <IconStopFilled />
                    Stop session
                </Item>
            )}
            {spaces.length > 0 && (
                <Sub
                    label={
                        <>
                            <IconFolder />
                            File to…
                        </>
                    }
                    title="File to…"
                    dataAttr={attr('file')}
                >
                    <TodaySpaceFileList
                        currentSpaceId={target.spaceId}
                        onSelect={(spaceId) => moveSession(sessionId, spaceId)}
                        itemDataAttr={attr('move')}
                        searchDataAttr={attr('move-search')}
                    />
                </Sub>
            )}
            {target.canHandOff && (
                <Item onClick={() => openHandoff(menuId)} dataAttr={attr('handoff')}>
                    <IconSend />
                    Hand off…
                </Item>
            )}
            {phoneLayout && surface === 'sidebar' && (
                <Item onClick={() => toggleSessionSelection(sessionId)} dataAttr={attr('select')}>
                    <IconCheckbox />
                    Select
                </Item>
            )}
            <Separator />
            <Item onClick={() => requestArchive(sessionId, menuId, activeRunId)} dataAttr={attr('archive')}>
                <IconArchive />
                {/* Only a running session asks first, so only its label promises a next step. */}
                {activeRunId ? 'Archive…' : 'Archive'}
                <Shortcut>{todayArchiveShortcutLabel(isMac())}</Shortcut>
            </Item>
        </>
    )
}
