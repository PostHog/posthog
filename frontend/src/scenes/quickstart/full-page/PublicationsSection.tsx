import { useActions, useValues } from 'kea'

import { QUICKSTART_BLOG_URL, QUICKSTART_NEWSLETTER_URL } from '../publications'
import { quickstartLogic } from '../quickstartLogic'
import { PublicationRail } from './PublicationRail'

export function PublicationsSection(): JSX.Element | null {
    const {
        blogPublications,
        blogPublicationsLoading,
        newsletterPublications,
        newsletterPublicationsLoading,
        publicationsHasMore,
    } = useValues(quickstartLogic)
    const { loadMoreBlogPublications, loadMoreNewsletterPublications } = useActions(quickstartLogic)

    const nothingToShow =
        !blogPublicationsLoading &&
        blogPublications.length === 0 &&
        !newsletterPublicationsLoading &&
        newsletterPublications.length === 0
    if (nothingToShow) {
        return null
    }

    return (
        <div className="flex flex-col gap-6">
            <PublicationRail
                feed="blog"
                title="Recent blog posts"
                viewAllUrl={QUICKSTART_BLOG_URL}
                viewAllLabel="View all posts"
                endLabel="Keep reading on the blog"
                publications={blogPublications}
                loading={blogPublicationsLoading}
                hasMore={publicationsHasMore.blog}
                onLoadMore={loadMoreBlogPublications}
            />
            <PublicationRail
                feed="newsletter"
                title="Recent build mode newsletter issues"
                viewAllUrl={QUICKSTART_NEWSLETTER_URL}
                viewAllLabel="Read & subscribe"
                endLabel="More issues + subscribe"
                publications={newsletterPublications}
                loading={newsletterPublicationsLoading}
                hasMore={publicationsHasMore.newsletter}
                onLoadMore={loadMoreNewsletterPublications}
            />
        </div>
    )
}
