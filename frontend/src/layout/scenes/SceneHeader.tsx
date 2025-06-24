import { IconCheck, IconChevronRight, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { cn } from 'lib/utils/css-classes'
import { CSSProperties, ReactNode, useEffect, useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { SceneHeaderChildItemProps, SceneHeaderItemProps, sceneHeaderLogic } from './sceneHeaderLogic'
import { breadcrumbsLogic } from '../navigation/Breadcrumbs/breadcrumbsLogic'

function renderChildItem(item: SceneHeaderChildItemProps): JSX.Element {
    if (item.type === 'link') {
        return (
            <DropdownMenuItem asChild key={item.id}>
                <Link
                    to={item.to}
                    buttonProps={{
                        menuItem: true,
                        ...item.buttonProps,
                    }}
                    onClick={item.onClick}
                >
                    {item.icon}
                    {item.title}
                </Link>
            </DropdownMenuItem>
        )
    }
    if (item.type === 'submenu') {
        return (
            <DropdownMenuSub key={item.id}>
                <DropdownMenuSubTrigger asChild>
                    <ButtonPrimitive menuItem>
                        {item.icon}
                        {item.title}
                        <IconChevronRight className="ml-auto size-3 text-tertiary" />
                    </ButtonPrimitive>
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>{item.children?.map((child) => renderChildItem(child))}</DropdownMenuSubContent>
            </DropdownMenuSub>
        )
    }
    return (
        <DropdownMenuItem asChild key={item.id}>
            <ButtonPrimitive menuItem onClick={item.onClick} {...item.buttonProps}>
                {item.icon}
                {item.title}
            </ButtonPrimitive>
        </DropdownMenuItem>
    )
}

interface Breadcrumb {
    name: ReactNode
    to: string
    id: string
    icon?: ReactNode
    iconColor?: string
}
interface SceneHeaderProps {
    pageTitle: string
    pageIcon?: ReactNode
    navItems: SceneHeaderItemProps[]
    children?: ReactNode
    pageTitleEditable?: boolean
    onPageTitleSubmit?: (title: string) => void
    handlePageTitleSubmit?: (title: string) => void
    breadcrumbs: Breadcrumb[]
}
export function SceneHeader({
    pageTitle,
    pageIcon,
    navItems,
    children,
    onPageTitleSubmit,
    pageTitleEditable = false,
    handlePageTitleSubmit,
    breadcrumbs,
}: SceneHeaderProps): JSX.Element {
    // const { loadedSceneSettingsSectionId } = useValues(topBarSettingsButtonLogic)
    // const { openSettingsPanel, closeSettingsPanel } = useActions(sidePanelSettingsLogic)
    // const { isOpen: isSettingsPanelOpen } = useValues(sidePanelSettingsLogic)
    // const { fileNewProps } = useValues(sceneHeaderLogic)
    const { setFileNewContainer } = useActions(sceneHeaderLogic)
    const headerRef = useRef<HTMLElement>(null)
    const sentinelRef = useRef<HTMLDivElement>(null)
    const [isSticky, setIsSticky] = useState(true)
    const [isPageTitleClicked, setIsPageTitleClicked] = useState(false)
    const [pageTitleValue, setPageTitleValue] = useState(pageTitle)
    const pageTitleEditableButtonRef = useRef<HTMLButtonElement>(null)
    const canSubmitPageTitleForm = pageTitleValue !== pageTitle
    const fontSizeClass = isSticky ? 'text-[16px]' : 'text-[18px]'
    // const { breadcrumbs, renameState } = useValues(breadcrumbsLogic)

    console.log('isSticky', isSticky)
    console.log('breadcrumbs', breadcrumbs)


    useEffect(() => {
        const mainContent = document.getElementById('main-content')
        const sentinel = sentinelRef.current

        if (!mainContent || !sentinel) {
            return
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                setIsSticky(!entry.isIntersecting)
            },
            {
                root: mainContent,
                threshold: 0,
                rootMargin: '-5px 0px 0px 0px',
            }
        )
        observer.observe(sentinel)

        return () => {
            observer.disconnect()
        }
    }, [])

    function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
        e.preventDefault()
        const data = new FormData(e.target as HTMLFormElement)
        onPageTitleSubmit?.(data.get('page-title') as string)
        setIsPageTitleClicked(false)
        handlePageTitleSubmit?.(data.get('page-title') as string)
    }

    function handleResetPageTitle(): void {
        setPageTitleValue(pageTitle)
        setIsPageTitleClicked(false)
        setTimeout(() => {
            pageTitleEditableButtonRef.current?.focus()
        }, 0)
    }

    function handlePageTitleInputBlur(): void {
        if (pageTitleValue !== pageTitle) {
            handlePageTitleSubmit?.(pageTitleValue)
        } else {
            handleResetPageTitle()
        }
    }

    function Title(): JSX.Element {
        console.log('pageTitle', pageTitle)
        return <h1 className={cn('font-semibold m-0 truncate max-w-[300px]', fontSizeClass)}>{pageTitle}</h1>
    }

    function RenderPageTitle(): JSX.Element {
        if (pageTitleEditable && isPageTitleClicked) {
            return (
                <form className="flex gap-1 w-full" onSubmit={handleSubmit}>
                    <TextInputPrimitive
                        name="page-title"
                        defaultValue={pageTitleValue}
                        onChange={(e) => setPageTitleValue(e.target.value)}
                        className={cn(
                            buttonPrimitiveVariants(),
                            'cursor-text font-semibold m-0 min-w-[300px]',
                            fontSizeClass
                        )}
                        autoFocus
                        onBlur={handlePageTitleInputBlur}
                    />
                    <div className="flex gap-px">
                        <ButtonPrimitive type="submit" disabled={!canSubmitPageTitleForm} iconOnly>
                            <IconCheck />
                        </ButtonPrimitive>
                        <ButtonPrimitive type="button" onClick={handleResetPageTitle} iconOnly>
                            <IconX />
                        </ButtonPrimitive>
                    </div>
                </form>
            )
        }
        if (pageTitleEditable) {
            return (
                <ButtonPrimitive
                    onClick={() => {
                        if (pageTitleEditable) {
                            setIsPageTitleClicked(!isPageTitleClicked)
                        }
                    }}
                    tooltip="Click to edit page title"
                    tooltipPlacement="top"
                    ref={pageTitleEditableButtonRef}
                >
                    <Title />
                </ButtonPrimitive>
            )
        }
        return <Title />
    }

    return (
        <>
            <div ref={sentinelRef} className="h-px" />
            <header
                className={cn('sticky top-0 z-50 py-2 bg-surface-secondary border-b border-primary px-4 -mx-4 mb-4', {
                    'h-[54px]': isSticky,
                    'h-[69px]': !isSticky,
                })}
                ref={headerRef}
                style={{
                    '--product-color': breadcrumbs && breadcrumbs.length ? breadcrumbs[0].iconColor : 'var(--bg-fill-button-tertiary-active)', 
                } as CSSProperties}
            >
                <div className="flex justify-center">
                    <div className="flex gap-[6px] flex-1 items-center">
                            <Link
                                to={breadcrumbs[0].to}
                                buttonProps={{
                                    size: 'base',
                                    className: cn(
                                        'size-[52px] bg-[var(--product-color)] hover:bg-[var(--product-color)] rounded flex justify-center items-center',
                                        isSticky && 'size-[30px]'
                                    ),
                                }}
                            >
                                <span
                                    className={cn(
                                        '[&_svg]:fill-white [&_svg]:size-[30px]',
                                        isSticky && '[&_svg]:size-[20px]'
                                    )}
                                >
                                    {pageIcon}
                                    </span>
                            </Link>
                        <div className={cn('relative flex-col gap-px items-center')}>
                            {!isSticky && (
                                <div className="flex items-center gap-1">
                                    {breadcrumbs.map((breadcrumb, index) => (
                                        <>
                                            {index > 0 && <IconChevronRight className="size-3 text-tertiary" />}
                                            <Link key={breadcrumb.id} to={breadcrumb.to} className="text-sm px-2 text-secondary hover:underline">
                                                {breadcrumb.name}
                                            </Link>
                                        </>
                                    ))}
                                </div>
                            )}
                            <RenderPageTitle />

                            {/* <ul className={cn('list flex gap-1 w-full flex-row')}>
                                {navItems.map((item) => (
                                    <li key={item.id}>
                                        {navItems.length > 0 && (
                                            <DropdownMenu>
                                                <DropdownMenuTrigger asChild>
                                                    <ButtonPrimitive>{item.title}</ButtonPrimitive>
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent
                                                    loop
                                                    align="start"
                                                    side="bottom"
                                                    className="max-w-[250px]"
                                                    ref={setFileNewContainer}
                                                >
                                                    {item.children?.map((child) => renderChildItem(child))}
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                        )}
                                    </li>
                                ))}
                            </ul> */}
                        </div>
                    </div>
                    <div className="flex-1 flex justify-end items-center">
                        {children}
                    </div>
                </div>
            </header>
        </>
    )
}
