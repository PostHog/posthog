import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import cloudflareLogo from 'public/cloudflare-logo.png'
import googleStorageLogo from 'public/google-cloud-storage-logo.png'
import s3Logo from 'public/s3-logo.png'

import { ManualLinkProvider as ManualLinkProviderType, sourceWizardLogic } from './sourceWizardLogic'

export const ManualLinkProvider = (): JSX.Element => {
    const { setManualLinkingProvider } = useActions(sourceWizardLogic)
    const onClick = (provider: ManualLinkProviderType): void => {
        setManualLinkingProvider(provider)
    }

    return (
        <div>
            <LemonButton onClick={() => onClick('aws')} fullWidth center type="secondary" className="mb-4">
                <div className="flex flex-row gap-2 justify-center items-center">
                    <img src={s3Logo} alt="AWS S3 logo" height={80} />
                    <div className="text-base">AWS S3</div>
                </div>
            </LemonButton>
            <LemonButton onClick={() => onClick('google-cloud')} fullWidth center type="secondary" className="mb-2">
                <div className="flex flex-row gap-2 justify-center items-center">
                    <img src={googleStorageLogo} alt="Google Cloud Storage logo" height={80} />
                    <div className="text-base">Google Cloud Storage</div>
                </div>
            </LemonButton>
            <LemonButton onClick={() => onClick('cloudflare-r2')} fullWidth center type="secondary" className="mb-2">
                <div className="flex flex-row gap-2 justify-center items-center">
                    <img src={cloudflareLogo} alt="Cloudflare logo" height={64} className="m-2" />
                    <div className="text-base">Cloudflare R2</div>
                </div>
            </LemonButton>
        </div>
    )
}
