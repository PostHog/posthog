import { useActions, useValues } from 'kea'

import { IconCalendar, IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { TodayAskBox } from './TodayAskBox'
import { FOLLOW_UP_OPTIONS } from './todayFixtures'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayStoryHeader } from './TodayStoryPage'
import { TodayStory } from './todayTypes'

export function TodayFollowUpPage({ story }: { story: TodayStory }): JSX.Element {
    const { followUpTimes } = useValues(todayLogic)
    const { setFollowUpTime, openStory } = useActions(todayLogic)
    const followUp = story.action.followUp
    const time = followUpTimes[story.id] ?? 'tomorrow'
    const cancelled = time === 'cancelled'
    const option = FOLLOW_UP_OPTIONS.find((candidate) => candidate.id === time) ?? FOLLOW_UP_OPTIONS[0]

    const items: LemonMenuItems = [
        {
            items: FOLLOW_UP_OPTIONS.map((candidate) => ({
                label: candidate.label,
                icon: !cancelled && candidate.id === time ? <IconCheck className="text-success" /> : undefined,
                onClick: () => setFollowUpTime(story.id, candidate.id),
            })),
        },
        ...(cancelled
            ? []
            : [
                  {
                      items: [
                          {
                              label: 'Cancel follow-up',
                              status: 'danger' as const,
                              onClick: () => setFollowUpTime(story.id, 'cancelled'),
                          },
                      ],
                  },
              ]),
    ]

    return (
        <div
            className="TodayStory Today__page"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--story-color': story.color } as React.CSSProperties}
        >
            <TodayStoryHeader kicker={`Follow-up · ${story.title}`} icon={<IconCalendar />} />
            <h1 className="TodayStory__heading">{followUp?.title ?? `Check back on ${story.title}`}</h1>
            <div className="TodayStory__body">
                <p>{followUp?.summary ?? 'I’ll look at this again and tell you if anything changed.'}</p>
            </div>
            <div className="TodaySchedule" role="status" data-cancelled={cancelled}>
                <i />
                <span>
                    {cancelled ? (
                        'Follow-up cancelled. Nothing will run.'
                    ) : (
                        <>
                            <span>Scheduled to trigger </span>
                            <strong>{option.phrase}</strong>
                        </>
                    )}
                </span>
                <LemonMenu items={items} placement="bottom-end">
                    <button type="button" className="TodaySecondary" data-attr="today-follow-up-edit">
                        <span>{cancelled ? 'Reschedule' : 'Edit'}</span>
                        <IconChevronDown />
                    </button>
                </LemonMenu>
            </div>
            <section className="TodayEvidence" aria-label="Follow-up evidence">
                <div className="Today__label">Evidence · 1 so far</div>
                <div className="TodayEvidence__row">
                    <button
                        type="button"
                        className="TodayEvidenceCard"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ '--evidence-color': story.color } as React.CSSProperties}
                        onClick={() => openStory(story.id)}
                    >
                        <span className="TodayEvidenceCard__top">
                            <span className="TodayTile relative">
                                <TodayIcon story={story.icon} />
                                <span className="TodayTile__check">
                                    <IconCheck />
                                </span>
                            </span>
                            <span>{story.title}</span>
                        </span>
                        <strong>{story.action.done ?? 'Completed'}</strong>
                        <p>{story.heading}</p>
                    </button>
                    <div className="TodayEvidenceCard TodayEvidenceCard--placeholder">
                        <span className="TodayEvidenceCard__top">
                            <span className="TodayTile">
                                <IconCalendar />
                            </span>
                            <span>Next run</span>
                        </span>
                        <strong>{cancelled ? 'Paused' : option.chip}</strong>
                        <p>
                            {cancelled
                                ? 'No new evidence will arrive while this is cancelled.'
                                : `New evidence lands here when this runs ${option.phrase}.`}
                        </p>
                    </div>
                </div>
            </section>
            <TodayAskBox compact />
        </div>
    )
}
