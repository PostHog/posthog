import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { PublicationFeedKey, QuickstartPublication } from '../publications'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'

export function PublicationCard({
    publication,
    feed,
}: {
    publication: QuickstartPublication
    feed: PublicationFeedKey
}): JSX.Element {
    return (
        <LemonCard hoverEffect className="p-0 overflow-hidden h-full rounded-lg border-transparent shadow-sm">
            <Link
                to={publication.url}
                target="_blank"
                className="flex flex-col h-full text-primary hover:text-primary"
                onClick={() =>
                    captureQuickstartAction('open_publication', undefined, {
                        feed,
                        publication_title: publication.title,
                        url: publication.url,
                    })
                }
                data-attr={`quickstart-publication-card-${feed}`}
            >
                {publication.imageUrl && (
                    <img
                        src={publication.imageUrl}
                        alt=""
                        className="w-full aspect-video object-cover bg-surface-secondary"
                        loading="lazy"
                        onError={(e) => {
                            e.currentTarget.style.display = 'none'
                        }}
                    />
                )}
                <div className="flex flex-col gap-1 p-3 flex-1">
                    <h3 className="font-semibold text-sm mb-0 line-clamp-2">{publication.title}</h3>
                    <p className="text-secondary text-xs mb-0 line-clamp-2 flex-1">{publication.description}</p>
                    <div className="text-xs text-tertiary mt-1">
                        {[
                            publication.author,
                            dayjs(publication.publishedAt).isValid() ? dayjs(publication.publishedAt).fromNow() : null,
                        ]
                            .filter(Boolean)
                            .join(' · ')}
                    </div>
                </div>
            </Link>
        </LemonCard>
    )
}
