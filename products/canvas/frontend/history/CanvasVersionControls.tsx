import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRedo, IconUndo } from '@posthog/icons'
import {
    Badge,
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import {
    canvasBuildStatusBadgeVariant,
    canvasBuildStatusLabel,
    canvasDraftTitle,
    canvasVersionByline,
    canvasVersionTitle,
} from './canvasHistoryLabels'
import { canvasHistoryLogic } from './canvasHistoryLogic'

function StepButton({
    label,
    disabledReason,
    onClick,
    dataAttr,
    children,
}: {
    label: string
    disabledReason: string | null
    onClick: () => void
    dataAttr: string
    children: JSX.Element
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        variant="outline"
                        aria-label={label}
                        disabled={!!disabledReason}
                        onClick={onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{disabledReason ?? label}</TooltipContent>
        </Tooltip>
    )
}

/** Undo and redo through versions, and the version and draft pickers, in the canvas header. */
export function CanvasVersionControls(): JSX.Element | null {
    const {
        versions,
        drafts,
        navigation,
        canUndo,
        canRedo,
        headVersionId,
        browseVersionId,
        browsedDraft,
        isGenerating,
    } = useValues(canvasHistoryLogic)
    const { undo, redo, setBrowseVersion } = useActions(canvasHistoryLogic)

    if (versions.length === 0 && drafts.length === 0) {
        return null
    }
    const generatingReason = isGenerating ? 'The agent is changing the canvas. Wait for it to finish.' : null

    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="canvas-version-controls">
            <ButtonGroup aria-label="Versions">
                <StepButton
                    label="Previous version"
                    disabledReason={generatingReason ?? (canUndo ? null : 'This is the oldest version.')}
                    onClick={undo}
                    dataAttr="canvas-version-undo"
                >
                    <IconUndo />
                </StepButton>
                <StepButton
                    label="Next version"
                    disabledReason={generatingReason ?? (canRedo ? null : 'This is the latest version.')}
                    onClick={redo}
                    dataAttr="canvas-version-redo"
                >
                    <IconRedo />
                </StepButton>
                {!browsedDraft && versions.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button size="sm" variant="outline" data-attr="canvas-version-menu">
                                    <span translate="no">{`v${versions.length - navigation.currentIndex}/${versions.length}`}</span>
                                    {!browseVersionId && <span>· Live</span>}
                                    <IconChevronDown />
                                </Button>
                            }
                        />
                        <DropdownMenuContent align="end" className="max-h-96 max-w-80 overflow-y-auto">
                            {versions.map((version, index) => (
                                <DropdownMenuItem
                                    key={version.id}
                                    onClick={() => setBrowseVersion(version.id === headVersionId ? null : version.id)}
                                    data-attr="canvas-version-menu-item"
                                >
                                    <ItemContent variant="menuItem">
                                        <ItemTitle className="truncate">
                                            {`v${versions.length - index}${version.id === headVersionId ? ' · Live' : ''} · ${canvasVersionTitle(version)}`}
                                        </ItemTitle>
                                        <ItemDescription className="leading-none">
                                            {canvasVersionByline(version)}
                                        </ItemDescription>
                                    </ItemContent>
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </ButtonGroup>
            {browsedDraft && <Badge variant="warning">Draft preview</Badge>}
            {drafts.length > 0 && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button size="sm" variant="outline" data-attr="canvas-drafts-menu">
                                <span>{`Drafts (${drafts.length})`}</span>
                                <IconChevronDown />
                            </Button>
                        }
                    />
                    <DropdownMenuContent align="end" className="max-h-96 max-w-80 overflow-y-auto">
                        {drafts.map((draft) => (
                            <DropdownMenuItem
                                key={draft.version_id}
                                onClick={() => setBrowseVersion(draft.version_id)}
                                data-attr="canvas-drafts-menu-item"
                            >
                                <ItemContent variant="menuItem">
                                    <ItemTitle className="truncate">{canvasDraftTitle(draft)}</ItemTitle>
                                </ItemContent>
                                <Badge variant={canvasBuildStatusBadgeVariant(draft.build_status)}>
                                    {canvasBuildStatusLabel(draft.build_status)}
                                </Badge>
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
