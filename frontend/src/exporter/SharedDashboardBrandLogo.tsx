import { backendAssetUrl } from 'lib/utils/apiHost'

export interface SharedDashboardBrandLogoProps {
    mediaId: string
}

export function SharedDashboardBrandLogo({ mediaId }: SharedDashboardBrandLogoProps): JSX.Element {
    return (
        <img
            className="block max-h-10 max-w-40 object-contain"
            src={backendAssetUrl(`/uploaded_media/${mediaId}`)}
            alt="Organization logo"
            data-attr="shared-dashboard-brand-logo"
        />
    )
}
