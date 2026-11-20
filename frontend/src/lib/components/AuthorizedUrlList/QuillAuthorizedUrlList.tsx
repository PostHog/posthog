import type { KeyboardEvent } from 'react'

import { IconChevronDown, IconCopy, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    ButtonGroup,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ExperimentIdType } from '~/types'

import { AuthorizedUrlForm } from './AuthorizedUrlForm'
import { AuthorizedUrlListType, KeyedAppUrl } from './authorizedUrlListLogic'
import { EmptyState } from './EmptyState'

export interface QuillAuthorizedUrlListProps {
    type: AuthorizedUrlListType
    actionId?: number
    experimentId?: ExperimentIdType
    productTourId?: string | null
    addText: string
    allowWildCards?: boolean
    displaySuggestions: boolean
    allowAdd: boolean
    allowDelete: boolean
    showLaunch: boolean
    launchInSameTab: boolean
    hideEmptyState: boolean
    urlsKeyed: KeyedAppUrl[]
    editUrlIndex: number | null
    isAddUrlFormVisible: boolean
    onlyAllowDomains: boolean
    writeDisabledReason: string | null
    isLaunchableType: boolean
    isHighlightedSuggestion: (keyedURL: KeyedAppUrl) => boolean
    canLaunchFromRow: (keyedURL: KeyedAppUrl) => boolean
    launchTargetFor: (url: string) => string
    onLaunch: (launchTarget: string) => void
    onRowKeyDown: (event: KeyboardEvent<HTMLElement>, launchTarget: string) => void
    onAdd: () => void
    onApplySuggestion: (url: string) => void
    onEdit: (originalIndex: number) => void
    onRemove: (url: string, index: number) => void
    onCopyLaunchCode: () => void
}

export function QuillAuthorizedUrlList({
    type,
    actionId,
    experimentId,
    productTourId,
    addText,
    allowWildCards,
    displaySuggestions,
    allowAdd,
    allowDelete,
    showLaunch,
    launchInSameTab,
    hideEmptyState,
    urlsKeyed,
    editUrlIndex,
    isAddUrlFormVisible,
    onlyAllowDomains,
    writeDisabledReason,
    isLaunchableType,
    isHighlightedSuggestion,
    canLaunchFromRow,
    launchTargetFor,
    onLaunch,
    onRowKeyDown,
    onAdd,
    onApplySuggestion,
    onEdit,
    onRemove,
    onCopyLaunchCode,
}: QuillAuthorizedUrlListProps): JSX.Element {
    const renderForm = (key?: string): JSX.Element => (
        <Item key={key} variant="outline" size="sm">
            <AuthorizedUrlForm
                type={type}
                actionId={actionId}
                experimentId={experimentId}
                productTourId={productTourId}
                allowWildCards={allowWildCards}
            />
        </Item>
    )

    return (
        <div className="flex flex-col gap-2" data-attr="authorized-urls-table">
            {!hideEmptyState && (
                <EmptyState
                    experimentId={experimentId}
                    productTourId={productTourId}
                    actionId={actionId}
                    type={type}
                    displaySuggestions={displaySuggestions}
                />
            )}

            {isAddUrlFormVisible ? (
                renderForm()
            ) : allowAdd ? (
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={onAdd}
                    data-attr="toolbar-add-url"
                    disabledReason={writeDisabledReason}
                >
                    <IconPlus />
                    {addText}
                </Button>
            ) : null}

            {urlsKeyed.map((keyedURL, index) => {
                if (!displaySuggestions && keyedURL.type === 'suggestion') {
                    return null
                }

                if (editUrlIndex === index) {
                    return renderForm(keyedURL.url)
                }

                const isHighlighted = isHighlightedSuggestion(keyedURL)
                const launchTarget = launchTargetFor(keyedURL.url)
                const isRowLaunchable = canLaunchFromRow(keyedURL)

                return (
                    <Item
                        key={keyedURL.url}
                        variant="outline"
                        size="sm"
                        className={cn(isRowLaunchable && 'cursor-pointer hover:bg-fill-hover')}
                        onClick={isRowLaunchable ? () => onLaunch(launchTarget) : undefined}
                        onKeyDown={isRowLaunchable ? (event) => onRowKeyDown(event, launchTarget) : undefined}
                        role={isRowLaunchable ? 'button' : undefined}
                        tabIndex={isRowLaunchable ? 0 : undefined}
                    >
                        <ItemContent className="min-w-0 flex-row items-center gap-2">
                            {keyedURL.type === 'suggestion' && (
                                <Tooltip>
                                    <TooltipTrigger render={<Badge variant="info" className="uppercase" />}>
                                        Suggestion
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        {'Seen in ' + keyedURL.count + ' events in the last 3 days'}
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            <Text size="xs" render={<span title={keyedURL.url} className="m-0 min-w-0 truncate" />}>
                                {keyedURL.url}
                            </Text>
                        </ItemContent>
                        <ItemActions className="shrink-0" onClick={(event) => event.stopPropagation()}>
                            {keyedURL.type === 'suggestion' && allowAdd ? (
                                <Button
                                    variant={isHighlighted ? 'primary' : 'default'}
                                    onClick={() => onApplySuggestion(keyedURL.url)}
                                    data-attr="toolbar-apply-suggestion"
                                    disabledReason={writeDisabledReason}
                                >
                                    <IconPlus />
                                    Apply suggestion
                                </Button>
                            ) : (
                                <>
                                    {showLaunch && (
                                        <ButtonGroup>
                                            <Button
                                                variant="outline"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive
                                                        to={launchTarget}
                                                        target={launchInSameTab ? undefined : '_blank'}
                                                    />
                                                }
                                                tooltip={
                                                    isLaunchableType
                                                        ? 'Open the toolbar on this page'
                                                        : 'Open the browser at this page'
                                                }
                                                data-attr="toolbar-open"
                                                disabledReason={
                                                    keyedURL.url.includes('*')
                                                        ? 'Wildcard domains cannot be launched'
                                                        : undefined
                                                }
                                            >
                                                <IconOpenInApp />
                                                Launch
                                            </Button>
                                            <Popover>
                                                <PopoverTrigger
                                                    render={
                                                        <Button
                                                            variant="outline"
                                                            size="icon"
                                                            aria-label="Launch options"
                                                            tooltip="Launch options"
                                                            data-attr="launch-toolbar-sideaction-dropdown"
                                                        />
                                                    }
                                                >
                                                    <IconChevronDown />
                                                </PopoverTrigger>
                                                <PopoverContent align="start" className="flex max-w-80 flex-col gap-2">
                                                    <Heading size="sm" render={<h3 className="m-0" />}>
                                                        If launching the toolbar didn't work,
                                                    </Heading>
                                                    <Text size="xs" render={<p className="m-0" />}>
                                                        You can copy the launch code and paste it into the browser
                                                        console on your site.
                                                    </Text>
                                                    <Text size="xs" render={<p className="m-0" />}>
                                                        NB you need to have added posthog to the `window`
                                                    </Text>
                                                    <div className="flex justify-end">
                                                        <Button
                                                            variant="primary"
                                                            data-attr="copy-manual-toolbar-launch-code"
                                                            onClick={onCopyLaunchCode}
                                                        >
                                                            <IconCopy />
                                                            Copy launch code
                                                        </Button>
                                                    </div>
                                                </PopoverContent>
                                            </Popover>
                                        </ButtonGroup>
                                    )}

                                    {allowAdd && (
                                        <Button
                                            size="icon"
                                            aria-label="Edit"
                                            tooltip="Edit"
                                            onClick={() => onEdit(keyedURL.originalIndex)}
                                            disabledReason={writeDisabledReason}
                                        >
                                            <IconPencil />
                                        </Button>
                                    )}

                                    {allowDelete && (
                                        <Button
                                            size="icon"
                                            aria-label={`Remove ${onlyAllowDomains ? 'domain' : 'URL'}`}
                                            tooltip={`Remove ${onlyAllowDomains ? 'domain' : 'URL'}`}
                                            onClick={() => onRemove(keyedURL.url, index)}
                                            disabledReason={writeDisabledReason}
                                        >
                                            <IconTrash />
                                        </Button>
                                    )}
                                </>
                            )}
                        </ItemActions>
                    </Item>
                )
            })}
        </div>
    )
}
