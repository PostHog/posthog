import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

interface VersionParts {
    major: number
    minor: number
    patch?: number
    preRelease?: string
    build?: string
}
//examples from semver spec
//Examples: 1.0.0-alpha+001, 1.0.0+20130313144700, 1.0.0-beta+exp.sha.5114f85, 1.0.0+21AF26D3—-117B344092BD.
//see https://semver.org/#backusnaur-form-grammar-for-valid-semver-versions
const splitVersion = (candidate: string): VersionParts => {
    const [head, build] = candidate.split('+')
    const [version, ...preRelease] = head.split('-')
    const [major, minor, patch] = version.split('.')
    return {
        major: Number(major),
        minor: Number(minor),
        patch: patch ? Number(patch) : undefined,
        preRelease: preRelease.join('-') || undefined,
        build,
    }
}

export function processEvent(event: PluginEvent, meta: LegacyTransformationPluginMeta) {
    if (!event.properties) {
        return
    }

    const properties = meta.config.properties as string
    const targetProperties = properties.split(',').map((s) => s.trim())

    for (const target of targetProperties) {
        const candidate = event.properties[target]
        meta.logger.log('found candidate property: ', target, ' matches ', candidate)
        if (candidate) {
            const { major, minor, patch, preRelease, build } = splitVersion(candidate)
            event.properties[`${target}__major`] = major
            event.properties[`${target}__minor`] = minor
            if (patch !== undefined) {
                event.properties[`${target}__patch`] = patch
            }
            if (preRelease !== undefined) {
                event.properties[`${target}__preRelease`] = preRelease
            }
            if (build !== undefined) {
                event.properties[`${target}__build`] = build
            }
        }
    }

    return event
}
