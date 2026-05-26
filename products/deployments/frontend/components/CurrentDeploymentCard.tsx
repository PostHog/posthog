import { IconExternal, IconGithub } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { Deployment, formatDuration } from '../fixtures'
import { DeploymentPreviewImage } from './DeploymentPreviewImage'
import { DeploymentStatusTag } from './DeploymentStatusTag'

export function CurrentDeploymentCard({ deployment: d }: { deployment: Deployment }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="overflow-hidden">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <DeploymentPreviewImage
                    src={d.preview_image_url ?? ''}
                    alt={`Preview of ${d.commit_message || d.id}`}
                    className="aspect-video md:aspect-auto md:h-full"
                    failed={d.status === 'error'}
                />
                <div className="flex flex-col gap-4">
                    {d.branch && <div className="font-mono text-sm text-secondary">{d.branch}</div>}
                    <div className="flex items-center gap-2 flex-wrap">
                        <CopyToClipboardInline description="deployment id" explicitValue={d.id}>
                            <span className="font-mono text-sm">{d.id}</span>
                        </CopyToClipboardInline>
                        {d.is_current && <LemonTag type="success">Current</LemonTag>}
                        <DeploymentStatusTag status={d.status} />
                    </div>
                    <div className="text-lg font-semibold">{d.commit_message || d.commit_sha || d.id}</div>
                    {d.status === 'error' && d.error_message && (
                        <div className="text-sm text-danger">
                            {d.error_step ? <strong>Failed at {d.error_step}: </strong> : null}
                            {d.error_message}
                        </div>
                    )}
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                        <dt className="text-secondary">Duration</dt>
                        <dd>{formatDuration(d.duration_seconds)}</dd>
                        <dt className="text-secondary">Deployed</dt>
                        <dd>
                            <TZLabel time={d.created_at} />
                        </dd>
                        <dt className="text-secondary">Author</dt>
                        <dd>
                            <ProfilePicture
                                user={{
                                    first_name: d.commit_author_name ?? '',
                                    email: d.commit_author_email ?? '',
                                }}
                                size="sm"
                                showName
                            />
                        </dd>
                    </dl>
                    <div className="flex gap-2 mt-auto pt-2">
                        {d.repo_url && d.commit_sha && (
                            <LemonButton
                                type="secondary"
                                to={`${d.repo_url}/commit/${d.commit_sha}`}
                                targetBlank
                                sideIcon={<IconGithub />}
                            >
                                View source
                            </LemonButton>
                        )}
                        {d.deployment_url && (
                            <LemonButton type="primary" to={d.deployment_url} targetBlank sideIcon={<IconExternal />}>
                                View live
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </LemonCard>
    )
}
