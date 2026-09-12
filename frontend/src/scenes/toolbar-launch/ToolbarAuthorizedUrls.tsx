import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { IconCopy, IconEllipsis, IconExternal, IconPencil, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'

export function ToolbarAuthorizedUrls({ canEdit }: { canEdit: boolean }): JSX.Element {
    const logic = authorizedUrlListLogic({
        actionId: null,
        experimentId: null,
        productTourId: null,
        type: AuthorizedUrlListType.TOOLBAR_URLS,
    })
    const {
        editUrlIndex,
        isAddUrlFormVisible,
        isProposedUrlSubmitting,
        launchUrl,
        proposedUrl,
        proposedUrlErrors,
        showProposedUrlErrors,
        suggestionsLoading,
        urlsKeyed,
    } = useValues(logic)
    const { currentTeamLoading } = useValues(teamLogic)
    const {
        addUrl,
        cancelProposingUrl,
        copyLaunchCode,
        loadSuggestions,
        newUrl,
        removeUrl,
        setEditUrlIndex,
        setProposedUrlValue,
        submitProposedUrl,
    } = useActions(logic)

    const visibleUrls = urlsKeyed.filter((url) => canEdit || url.type === 'authorized')
    const urlForm = (
        <form
            className="flex w-full flex-col gap-4"
            onSubmit={(event) => {
                event.preventDefault()
                submitProposedUrl()
            }}
        >
            <Field>
                <FieldLabel htmlFor="toolbar-authorized-url">URL</FieldLabel>
                <Input
                    id="toolbar-authorized-url"
                    autoFocus
                    value={proposedUrl.url}
                    placeholder="Enter a URL, for example https://posthog.com"
                    data-attr="url-input"
                    aria-invalid={showProposedUrlErrors && !!proposedUrlErrors.url}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setProposedUrlValue('url', event.target.value)}
                />
                {showProposedUrlErrors && <FieldError>{proposedUrlErrors.url}</FieldError>}
            </Field>
            <div className="flex flex-wrap justify-end gap-2">
                <Button type="button" variant="outline" onClick={cancelProposingUrl}>
                    Cancel
                </Button>
                <Button type="submit" variant="primary" loading={isProposedUrlSubmitting} data-attr="url-save">
                    Save URL
                </Button>
            </div>
        </form>
    )

    return (
        <div className="flex flex-col gap-4" data-attr="authorized-urls-table">
            {isAddUrlFormVisible ? (
                urlForm
            ) : canEdit ? (
                <Button variant="outline" onClick={newUrl} data-attr="toolbar-add-url" className="w-fit">
                    <IconPlus />
                    Add authorized URL
                </Button>
            ) : null}

            {visibleUrls.length === 0 && !isAddUrlFormVisible ? (
                <Empty className="min-h-48">
                    <EmptyHeader>
                        <EmptyTitle>{suggestionsLoading ? 'Looking for URLs' : 'No authorized URLs'}</EmptyTitle>
                        <EmptyDescription>
                            {suggestionsLoading
                                ? 'Checking recent events for URLs you can authorize.'
                                : canEdit
                                  ? 'Add a URL to launch the toolbar on your website.'
                                  : 'Ask a project editor to add an authorized URL.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    {canEdit && (
                        <EmptyContent>
                            <Button
                                variant="outline"
                                loading={suggestionsLoading}
                                onClick={loadSuggestions}
                                data-attr="authorized-url-list-fetch-suggestions"
                            >
                                <IconRefresh />
                                Check for suggestions
                            </Button>
                        </EmptyContent>
                    )}
                </Empty>
            ) : (
                <ItemGroup combined>
                    {visibleUrls.map((keyedURL, index) => {
                        if (keyedURL.type === 'authorized' && editUrlIndex === keyedURL.originalIndex) {
                            return (
                                <Item key={`${keyedURL.type}-${keyedURL.url}`} size="sm" variant="outline">
                                    {urlForm}
                                </Item>
                            )
                        }

                        const target = launchUrl(keyedURL.url)
                        const isWildcard = keyedURL.url.includes('*')

                        return (
                            <Item key={`${keyedURL.type}-${keyedURL.url}`} size="sm" variant="outline">
                                <ItemContent className="min-w-0">
                                    <ItemTitle className="flex min-w-0 items-center">
                                        {keyedURL.type === 'suggestion' && <Badge variant="info">Suggestion</Badge>}
                                        <span className="truncate" title={keyedURL.url}>
                                            {keyedURL.url}
                                        </span>
                                    </ItemTitle>
                                    {keyedURL.type === 'suggestion' && (
                                        <ItemDescription>
                                            Seen in {keyedURL.count ?? 0} events in the last 3 days
                                        </ItemDescription>
                                    )}
                                </ItemContent>
                                <ItemActions className="flex-wrap justify-end">
                                    {keyedURL.type === 'suggestion' ? (
                                        <Button
                                            variant="primary"
                                            size="sm"
                                            loading={currentTeamLoading}
                                            onClick={() => addUrl(keyedURL.url)}
                                            data-attr="toolbar-apply-suggestion"
                                        >
                                            <IconPlus />
                                            Authorize
                                        </Button>
                                    ) : (
                                        <>
                                            {isWildcard ? (
                                                <Tooltip>
                                                    <TooltipTrigger
                                                        render={
                                                            <Button variant="primary" size="sm" disabled>
                                                                <IconExternal />
                                                                Launch
                                                            </Button>
                                                        }
                                                    />
                                                    <TooltipContent>Wildcard URLs cannot be launched</TooltipContent>
                                                </Tooltip>
                                            ) : (
                                                <Button
                                                    variant="primary"
                                                    size="sm"
                                                    render={<LinkPrimitive to={target} target="_blank" />}
                                                    data-attr="toolbar-open"
                                                >
                                                    <IconExternal />
                                                    Launch
                                                </Button>
                                            )}
                                            <DropdownMenu>
                                                <DropdownMenuTrigger
                                                    render={
                                                        <Button
                                                            variant="default"
                                                            size="icon-sm"
                                                            aria-label="More launch options"
                                                            data-attr="launch-toolbar-sideaction-dropdown"
                                                        />
                                                    }
                                                >
                                                    <IconEllipsis />
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent align="end" className="w-auto min-w-max">
                                                    <DropdownMenuItem
                                                        onClick={copyLaunchCode}
                                                        data-attr="copy-manual-toolbar-launch-code"
                                                    >
                                                        <IconCopy />
                                                        Copy manual launch code
                                                    </DropdownMenuItem>
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                            {canEdit && (
                                                <Tooltip>
                                                    <TooltipTrigger
                                                        render={
                                                            <Button
                                                                variant="default"
                                                                size="icon-sm"
                                                                aria-label={`Edit ${keyedURL.url}`}
                                                                onClick={() => setEditUrlIndex(keyedURL.originalIndex)}
                                                            />
                                                        }
                                                    >
                                                        <IconPencil />
                                                    </TooltipTrigger>
                                                    <TooltipContent>Edit URL</TooltipContent>
                                                </Tooltip>
                                            )}
                                            {canEdit && (
                                                <AlertDialog>
                                                    <Tooltip>
                                                        <TooltipTrigger
                                                            render={
                                                                <AlertDialogTrigger
                                                                    render={
                                                                        <Button
                                                                            variant="default"
                                                                            size="icon-sm"
                                                                            aria-label={`Remove ${keyedURL.url}`}
                                                                            disabled={currentTeamLoading}
                                                                        />
                                                                    }
                                                                />
                                                            }
                                                        >
                                                            <IconTrash />
                                                        </TooltipTrigger>
                                                        <TooltipContent>Remove URL</TooltipContent>
                                                    </Tooltip>
                                                    <AlertDialogContent>
                                                        <AlertDialogHeader>
                                                            <AlertDialogTitle>
                                                                Remove this authorized URL?
                                                            </AlertDialogTitle>
                                                            <AlertDialogDescription>
                                                                {keyedURL.url}
                                                            </AlertDialogDescription>
                                                        </AlertDialogHeader>
                                                        <AlertDialogFooter>
                                                            <AlertDialogClose render={<Button variant="outline" />}>
                                                                Cancel
                                                            </AlertDialogClose>
                                                            <AlertDialogClose
                                                                render={
                                                                    <Button
                                                                        variant="destructive-outline"
                                                                        loading={currentTeamLoading}
                                                                        onClick={() => removeUrl(index)}
                                                                    />
                                                                }
                                                            >
                                                                Remove
                                                            </AlertDialogClose>
                                                        </AlertDialogFooter>
                                                    </AlertDialogContent>
                                                </AlertDialog>
                                            )}
                                        </>
                                    )}
                                </ItemActions>
                            </Item>
                        )
                    })}
                </ItemGroup>
            )}

            {visibleUrls.length > 0 && canEdit && (
                <Button
                    variant="link-muted"
                    size="sm"
                    loading={suggestionsLoading}
                    onClick={loadSuggestions}
                    data-attr="authorized-url-list-fetch-suggestions"
                    className="w-fit"
                >
                    <IconRefresh />
                    Check for more suggestions
                </Button>
            )}
            {!canEdit && (
                <Text size="xs" variant="muted">
                    You can launch the toolbar, but only project editors can change authorized URLs.
                </Text>
            )}
        </div>
    )
}
