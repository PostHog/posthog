import { Link } from 'lib/lemon-ui/Link'
import { backendAssetUrl } from 'lib/utils/apiHost'

export interface SharedDashboardBrandLogoProps {
    mediaId: string
    linkUrl?: string
}

export function SharedDashboardBrandLogo({ mediaId, linkUrl }: SharedDashboardBrandLogoProps): JSX.Element {
    const logo = (
        <img
            className="block max-h-10 max-w-40 object-contain"
            src={backendAssetUrl(`/uploaded_media/${mediaId}`)}
            alt="Logo"
            data-attr="shared-dashboard-brand-logo"
        />
    )
    if (!linkUrl) {
        return logo
    }
    return (
        <Link to={linkUrl} target="_blank" className="inline-block">
            {logo}
        </Link>
    )
}
