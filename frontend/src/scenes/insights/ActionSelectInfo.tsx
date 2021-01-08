import { Divider } from 'antd'
import React from 'react'
import { ActionType } from '~/types'

function eventToHumanName(event: string): string {
    return event && event[0] == '$' ? event[1].toUpperCase() + event.slice(2) : event
}

export function ActionSelectInfo({ entity }: { entity: ActionType }): JSX.Element {
    if (!entity) {
        return null
    }
    return (
        <div className="select-box-info">
            {entity.steps &&
                entity.steps.map((step, index) => (
                    <div key={step.id}>
                        <strong>
                            Match group {index + 1}: {step.event && eventToHumanName(step.event)}
                        </strong>
                        <ul>
                            {step.selector && (
                                <li>
                                    CSS selector matches
                                    <pre>{step.selector}</pre>
                                </li>
                            )}
                            {step.tag_name && (
                                <li>
                                    Tag name matches <pre>{step.tag_name}</pre>
                                </li>
                            )}
                            {step.text && (
                                <li>
                                    Text matches <pre>{step.text}</pre>
                                </li>
                            )}
                            {step.href && (
                                <li>
                                    Link HREF matches <pre>{step.href}</pre>
                                </li>
                            )}
                            {step.url && (
                                <li>
                                    URL{' '}
                                    {step.url_matching === 'regex'
                                        ? 'matches regex'
                                        : step.url_matching === 'exact'
                                        ? 'matches exactly'
                                        : 'contains'}{' '}
                                    <pre>{step.url}</pre>
                                </li>
                            )}
                        </ul>
                        {entity.steps && index < entity.steps.length - 1 && <Divider>OR</Divider>}
                    </div>
                ))}
        </div>
    )
}
