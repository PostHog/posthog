import './SentenceList.scss'

export interface SentenceListProps {
    listParts: (string | JSX.Element | null)[]
    prefix?: string | JSX.Element | null
    suffix?: string | JSX.Element | null
}

/** Transforms a list of phrases into a cohesive English sentence using commas and the word 'and' where appropriate */
export function SentenceList({ listParts, prefix = null, suffix = null }: SentenceListProps): JSX.Element {
    return (
        <div className="sentence-list">
            {prefix && <div className="sentence-part">{prefix}&nbsp;</div>}
            <>
                {listParts
                    .filter((part) => !!part)
                    .flatMap((part, index, all) => {
                        const isntFirst = index > 0
                        const isLast = index === all.length - 1
                        const atLeastThree = all.length >= 2
                        return [
                            isntFirst && (
                                <div className="sentence-part" key={`${index}-a`}>
                                    ,{' '}
                                </div>
                            ),
                            isLast && atLeastThree && (
                                <div className="sentence-part" key={`${index}-b`}>
                                    &nbsp;and&nbsp;
                                </div>
                            ),
                            <div className="sentence-part" key={`${index}-c`}>
                                {part}
                            </div>,
                        ]
                    })}
            </>
            {suffix && <div className="sentence-part">&nbsp;{suffix}</div>}
        </div>
    )
}
