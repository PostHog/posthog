import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

import { todayShellLogic } from './todayShellLogic'

const TITLE_SCROLL_THRESHOLD = 56

export function TodayPhoneHeader(): JSX.Element {
    const { sceneBreadcrumbs } = useValues(breadcrumbsLogic)
    const { goBackOnPhone } = useActions(todayShellLogic)
    const [scrolled, setScrolled] = useState(false)
    const title = [...sceneBreadcrumbs].reverse().find((breadcrumb) => !!breadcrumb.name)?.name

    useEffect(() => {
        const main = document.getElementById('main-content')
        if (!main) {
            return
        }
        const onScroll = (): void => setScrolled(main.scrollTop > TITLE_SCROLL_THRESHOLD)
        onScroll()
        main.addEventListener('scroll', onScroll, { passive: true })
        return () => main.removeEventListener('scroll', onScroll)
    }, [title])

    return (
        <header className="TodayPhoneHeader" data-scrolled={scrolled} data-quill>
            <Button
                size="icon-lg"
                className="rounded-full"
                aria-label="Back"
                data-attr="today-phone-back"
                onClick={goBackOnPhone}
            >
                <IconChevronLeft />
            </Button>
            <Text
                render={<span />}
                weight="semibold"
                className="TodayPhoneHeader__title min-w-0 flex-1 truncate"
                aria-hidden={!scrolled}
            >
                {title}
            </Text>
        </header>
    )
}
