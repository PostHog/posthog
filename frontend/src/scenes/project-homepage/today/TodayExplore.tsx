import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { TodayHomeHeading } from './TodayHomeHeading'
import { todayLogic } from './todayLogic'

const EXPLORE_SHOWN = 4

export function TodayExplore(): JSX.Element {
    const { exploreItems } = useValues(todayLogic)
    const { exploreOpened } = useActions(todayLogic)
    const { pickPane } = useActions(todayShellLogic)
    const titleId = useId()
    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Try a product</TodayHomeHeading>
                <Button
                    variant="link-muted"
                    size="sm"
                    className="-mx-2 -my-1 text-[13px]"
                    onClick={() => pickPane('products')}
                    data-attr="today-home-explore-all"
                >
                    All products
                </Button>
            </div>
            <ul className="TodayJumpList TodayJumpList--explore">
                {exploreItems.slice(0, EXPLORE_SHOWN).map((item, position) => (
                    <li key={item.product} className="TodayJumpRow">
                        <TodayObjectIcon type={item.icon} className="TodayJumpRow__icon" />
                        <div className="min-w-0">
                            <LinkPrimitive
                                to={item.to()}
                                className="TodayJumpRow__link"
                                onClick={() => exploreOpened(item.product, position)}
                                data-attr="today-home-explore"
                            >
                                {item.name}
                            </LinkPrimitive>
                            <span className="TodayJumpRow__meta">{item.description}</span>
                        </div>
                    </li>
                ))}
            </ul>
        </section>
    )
}
