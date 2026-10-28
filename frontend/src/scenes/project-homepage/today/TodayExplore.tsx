import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import { TodayHomeHeading } from './TodayHomeHeading'
import { todayLogic } from './todayLogic'

export function TodayExplore(): JSX.Element {
    const { exploreItems } = useValues(todayLogic)
    const { exploreOpened } = useActions(todayLogic)
    const titleId = useId()
    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Explore</TodayHomeHeading>
            </div>
            <ul className="TodayJumpList TodayJumpList--explore">
                {exploreItems.map((item, position) => (
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
