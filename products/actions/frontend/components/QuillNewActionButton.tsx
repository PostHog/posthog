import { IconChevronDown, IconCursorClick, IconPencil } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function QuillNewActionButton({ onSelectOption }: { onSelectOption?: () => void }): JSX.Element {
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Action, AccessControlLevel.Editor)

    return (
        <ButtonGroup>
            <AccessControlAction
                resourceType={AccessControlResourceType.Action}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Shortcut
                    name="NewAction"
                    keybind={[keyBinds.new]}
                    intent="New action"
                    interaction="click"
                    scope={Scene.Actions}
                >
                    <Button
                        variant="primary"
                        render={
                            <LinkPrimitive
                                to={disabledReason ? undefined : urls.createAction()}
                                onClick={onSelectOption}
                            />
                        }
                        data-attr="create-action"
                        tooltip="New action"
                    >
                        New action
                    </Button>
                </Shortcut>
            </AccessControlAction>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="More ways to create an action"
                            disabledReason={disabledReason}
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-80">
                    <DropdownMenuItem
                        render={
                            <Button
                                size="row"
                                left
                                render={
                                    <LinkPrimitive
                                        to={disabledReason ? undefined : urls.createAction()}
                                        onClick={onSelectOption}
                                    />
                                }
                            />
                        }
                        data-attr="new-action-pageview"
                        description={
                            <>
                                Match events by name, URL patterns, or custom properties.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/data/actions"
                                            target="_blank"
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    }
                                >
                                    Learn more
                                </Button>
                            </>
                        }
                    >
                        <IconPencil />
                        From event or pageview
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        render={<Button size="row" left render={<LinkPrimitive to={urls.toolbarLaunch()} />} />}
                        data-attr="new-action-inspect"
                        description={
                            <>
                                Use the toolbar to visually select elements on your site.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/toolbar/create-toolbar-actions"
                                            target="_blank"
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    }
                                >
                                    Learn more
                                </Button>
                            </>
                        }
                    >
                        <IconCursorClick />
                        Inspect element on site
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
