import DOMPurify from 'dompurify'

// Keep in sync with MEMBER_NOTICE_ALLOWED_TAGS in posthog/api/organization.py. The backend already sanitizes on save,
// this second pass guards against a notice written before the allowlist changed.
const MEMBER_NOTICE_SANITIZE_CONFIG = {
    ALLOWED_TAGS: ['a', 'b', 'br', 'code', 'em', 'i', 'li', 'ol', 'p', 's', 'span', 'strong', 'u', 'ul'],
    ALLOWED_ATTR: ['href', 'title', 'rel'],
    ADD_ATTR: ['target'],
}

export function OrganizationMemberNoticeMessage({ html }: { html: string }): JSX.Element {
    return (
        <span
            className="[&_a]:text-link [&_a]:underline [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5"
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html, MEMBER_NOTICE_SANITIZE_CONFIG) }}
        />
    )
}
