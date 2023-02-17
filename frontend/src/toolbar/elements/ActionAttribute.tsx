import { IconBranch, IconClipboardEdit, IconLink, IconTextSize } from 'lib/lemon-ui/icons'

function SelectorString({ value }: { value: string }): JSX.Element {
    const [last, ...rest] = value.split(' ').reverse()
    const selector = (
        <span>
            {rest.reverse().join(' ')} <strong>{last}</strong>
        </span>
    )

    return (
        <>
            <div className="flex flex-row items-center">{selector}</div>
        </>
    )
}

export function ActionAttribute({ attribute, value }: { attribute: string; value?: string }): JSX.Element {
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
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
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
            <div className="text-muted text-xl">{icon}</div>
            <div className="grow">{text}</div>
        </div>
    )
}
