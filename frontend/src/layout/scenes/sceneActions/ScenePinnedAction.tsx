import { IconChevronDown } from '@posthog/icons'
import {
    ActionMenu,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    PopoverTrigger,
    cn,
} from '@posthog/quill'

import { captureSceneMenuBar } from '../components/captureSceneMenuBar'
import type { SceneAction, ScenePinned } from './sceneActionModel'

const VARIANTS = { primary: 'primary', secondary: 'outline', icon: 'outline' } as const

function captureClick(action: SceneAction): void {
    // pinned: analytics property values are wire strings
    captureSceneMenuBar('scene menu bar item clicked', {
        item: action.dataAttr ?? action.id,
        layout: 'scene-actions',
        surface: 'title',
    })
}

export function ScenePinnedAction({ action }: { action: SceneAction & { pinned: ScenePinned } }): JSX.Element {
    const { pinned } = action
    if (pinned.render) {
        return <>{pinned.render()}</>
    }
    const iconOnly = pinned.variant === 'icon'
    const buttonProps = {
        variant: VARIANTS[pinned.variant],
        size: iconOnly ? ('icon' as const) : undefined,
        'aria-label': iconOnly ? action.label : undefined,
        tooltip: iconOnly ? action.label : action.tooltip,
        disabledReason: action.disabledReason,
        'data-attr': pinned.dataAttr ?? `${action.dataAttr ?? action.id}-title`,
    }
    const content = iconOnly ? (
        action.icon
    ) : (
        <>
            {action.icon}
            {action.label}
        </>
    )

    switch (action.type) {
        case 'checkbox':
            return (
                <Button
                    {...buttonProps}
                    aria-pressed={action.checked}
                    className={cn(action.checked && 'bg-fill-selected')}
                    onClick={() => {
                        captureClick(action)
                        action.onCheckedChange(!action.checked)
                    }}
                >
                    {content}
                </Button>
            )
        case 'radio': {
            const current = action.options.find((option) => option.value === action.value)
            return (
                <DropdownMenu>
                    <DropdownMenuTrigger render={<Button {...buttonProps} />}>
                        {current?.icon ?? action.icon}
                        {!iconOnly && (
                            <>
                                {current?.label ?? action.label}
                                <IconChevronDown />
                            </>
                        )}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuRadioGroup
                            value={action.value}
                            onValueChange={(value) => {
                                captureClick(action)
                                action.onValueChange(value)
                            }}
                        >
                            {action.options.map((option) => (
                                <DropdownMenuRadioItem
                                    key={option.value}
                                    value={option.value}
                                    disabledReason={option.disabledReason}
                                >
                                    {option.icon}
                                    {option.label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )
        }
        case 'submenu':
            return (
                <ActionMenu
                    items={action.items}
                    searchable={false}
                    align="end"
                    trigger={<Button {...buttonProps} />}
                    triggerChildren={
                        <>
                            {content}
                            {!iconOnly && <IconChevronDown />}
                        </>
                    }
                    onItemSelect={(item) =>
                        captureSceneMenuBar('scene menu bar item clicked', {
                            item: item.dataAttr ?? item.id,
                            layout: 'scene-actions',
                            surface: 'title',
                        })
                    }
                />
            )
        case 'panel':
            return (
                <Popover>
                    <PopoverTrigger render={<Button {...buttonProps} />} onClick={() => captureClick(action)}>
                        {content}
                    </PopoverTrigger>
                    <PopoverContent align="end" className={cn('flex w-80 flex-col gap-2 p-2', action.panelClassName)}>
                        {action.render()}
                    </PopoverContent>
                </Popover>
            )
        default:
            return (
                <Button
                    {...buttonProps}
                    variant={action.destructive ? 'destructive-outline' : buttonProps.variant}
                    onClick={() => {
                        captureClick(action)
                        action.onSelect()
                    }}
                >
                    {content}
                </Button>
            )
    }
}
