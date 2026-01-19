import { LemonInputSelect, Link } from '@posthog/lemon-ui'

// NEEDED? ALREDY EXISTS? CORRECT NAME?
export function MultiSelectFilterDropdown(props: {
    title: string
    placeholder: string
    options: { key: string; label: string }[]
    values: string[]
    setValues: (values: string[]) => void
}): JSX.Element {
    return (
        <div className="w-96 p-1 space-y-3">
            <div className="flex justify-between items-center">
                <h5 className="mb-0">{props.title}</h5>
                {props.values.length ? (
                    <Link
                        to="#"
                        onClick={(e) => {
                            e.preventDefault()
                            props.setValues([])
                        }}
                    >
                        Clear
                    </Link>
                ) : null}
            </div>
            <LemonInputSelect
                value={props.values}
                onChange={props.setValues}
                mode="multiple"
                placeholder={props.placeholder}
                options={props.options}
            />
        </div>
    )
}
