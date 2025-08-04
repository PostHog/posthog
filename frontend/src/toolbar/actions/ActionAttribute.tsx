import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconBranch, IconClipboardEdit, IconLink, IconTextSize } from 'lib/lemon-ui/icons'

import { actionsTabLogic } from './actionsTabLogic'
import { ActionStepPropertyKey } from './ActionStep'

function SelectorString({ value }: { value: string }): JSX.Element {
    const [last, ...rest] = value.split(' ').reverse()
    return (
        <>
            {rest.reverse().join(' ')} <strong>{last}</strong>
        </>
    )
}

export function ActionAttribute({
    attribute,
    value,
}: {
    attribute: ActionStepPropertyKey
    value?: string
}): JSX.Element {
    const { automaticCreationIncludedPropertyKeys, automaticActionCreationEnabled } = useValues(actionsTabLogic)
    const { removeAutomaticCreationIncludedPropertyKey, addAutomaticCreationIncludedPropertyKey } =
        useActions(actionsTabLogic)
    const icon =
        attribute === 'text' ? (
            <IconTextSize />
        ) : attribute === 'href' ? (
            <IconLink />
        ) : attribute === 'selector' ? (
            <IconBranch />
        ) : (
            <IconClipboardEdit />
        )

    const text =
        attribute === 'href' ? (
            <Link to={value} target="_blank">
                {value}
            </Link>
        ) : attribute === 'selector' ? (
            value ? (
                <span className="font-mono">
                    <SelectorString value={value} />
                </span>
            ) : (
                <span>
                    Could not generate a unique selector for this element. Please instrument it with a unique{' '}
                    <code>id</code> or <code>data-attr</code> attribute.
                </span>
            )
        ) : (
            value
        )

    return (
        <div key={attribute} className="flex flex-row gap-2 justify-between items-center">
            {automaticActionCreationEnabled && (
                <LemonSwitch
                    size="small"
                    checked={automaticCreationIncludedPropertyKeys.includes(attribute)}
                    onChange={(checked) =>
                        checked
                            ? addAutomaticCreationIncludedPropertyKey(attribute)
                            : removeAutomaticCreationIncludedPropertyKey(attribute)
                    }
                    sliderColorOverrideChecked="color-accent"
                    sliderColorOverrideUnchecked="color-secondary-foreground"
                />
            )}
            <div className="text-secondary-foreground text-xl">{icon}</div>
            <div className="text-foreground grow">{text}</div>
        </div>
    )
}
