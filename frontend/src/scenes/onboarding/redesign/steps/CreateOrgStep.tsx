import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCheck, IconChevronDown, IconPerson } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { Region } from '~/types'

import { RoleSelectModal } from '../components/RoleSelectModal'
import { findRole } from '../data/roles'
import { onboardingLogic } from '../onboardingLogic'

const REGION_DISPLAY: Partial<Record<Region, { label: string; flag: string }>> = {
    [Region.US]: { label: 'United States', flag: '🇺🇸' },
    [Region.EU]: { label: 'European Union', flag: '🇪🇺' },
}

function SignedInChip(): JSX.Element | null {
    const { user } = useValues(userLogic)
    if (!user?.email) {
        return null
    }
    const initial = (user.first_name?.[0] || user.email[0] || 'Y').toUpperCase()
    return (
        <div className="inline-flex items-center gap-2 rounded-full border border-primary bg-surface-primary py-1 pl-1 pr-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">
                {initial}
            </span>
            <span className="text-secondary text-sm">
                Signed in as <span className="font-semibold text-default">{user.email}</span>
            </span>
            <span className="text-success inline-flex items-center gap-1 text-xs font-semibold">
                <IconCheck /> verified
            </span>
        </div>
    )
}

/** Read-only data-region chip. Region is fixed per cloud deployment; switching means redirecting to the other cloud. */
function DataRegionField(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const region = preflight?.region
    if (!preflight?.cloud || !region || !REGION_DISPLAY[region]) {
        return null
    }
    const display = REGION_DISPLAY[region]
    const otherRegion = region === Region.US ? Region.EU : Region.US
    const switchRegion = (): void => {
        const { pathname, search, hash } = router.values.currentLocation
        window.location.href = `https://${CLOUD_HOSTNAMES[otherRegion]}${pathname}${search}${hash}`
    }
    return (
        <LemonField.Pure label="Data region">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <div className="inline-flex items-center gap-2 rounded border border-primary bg-surface-primary px-3 py-2">
                    <span className="text-base leading-none">{display?.flag}</span>
                    <span className="text-sm font-semibold text-default">{display?.label}</span>
                    <IconCheck className="text-success" />
                </div>
                <span className="text-secondary text-xs">
                    Set at sign-up.{' '}
                    <button type="button" onClick={switchRegion} className="text-accent font-semibold">
                        Switch to {REGION_DISPLAY[otherRegion]?.label}
                    </button>
                </span>
            </div>
        </LemonField.Pure>
    )
}

/** Step 0: create the organization — your name, org name, role, and the (fixed) data region. */
export function CreateOrgStep(): JSX.Element {
    const { name, organizationName, roleId } = useValues(onboardingLogic)
    const { setName, setOrganizationName, setRole } = useActions(onboardingLogic)
    const [roleModalOpen, setRoleModalOpen] = useState(false)
    const selectedRole = findRole(roleId)

    return (
        <div className="max-w-lg">
            <SignedInChip />
            <h1 className="mt-5 text-3xl font-bold text-default">Let's set up your organization.</h1>
            <div className="mt-6 flex flex-col gap-4">
                <LemonField.Pure label="Your name">
                    <LemonInput value={name} onChange={setName} placeholder="Jordan Rivera" autoFocus />
                </LemonField.Pure>
                <LemonField.Pure label="Organization name">
                    <LemonInput value={organizationName} onChange={setOrganizationName} placeholder="Acme Inc." />
                </LemonField.Pure>
                <LemonField.Pure
                    label={
                        <span>
                            Your role <span className="text-muted font-normal">· optional</span>
                        </span>
                    }
                >
                    <button
                        type="button"
                        onClick={() => setRoleModalOpen(true)}
                        className="flex items-center gap-3 rounded-lg border border-primary bg-surface-primary p-2 text-left transition-colors hover:border-accent"
                    >
                        <span className="flex h-12 w-12 shrink-0 items-end justify-center overflow-hidden rounded bg-surface-secondary">
                            {selectedRole ? (
                                <selectedRole.Hog className="h-11 w-auto" />
                            ) : (
                                <IconPerson className="text-muted m-auto text-xl" />
                            )}
                        </span>
                        <span className="flex-1">
                            <span className="block font-semibold text-default">
                                {selectedRole ? selectedRole.label : 'Select your role'}
                            </span>
                            {selectedRole && <span className="text-secondary block text-xs">{selectedRole.blurb}</span>}
                        </span>
                        <IconChevronDown className="text-muted shrink-0" />
                    </button>
                </LemonField.Pure>
                <DataRegionField />
            </div>
            <RoleSelectModal
                isOpen={roleModalOpen}
                selectedRoleId={roleId}
                onSelect={(id) => {
                    setRole(id)
                    setRoleModalOpen(false)
                }}
                onClose={() => setRoleModalOpen(false)}
            />
        </div>
    )
}
