import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { matchesSettingAccessControl } from './accessGating'

const gate = {
    resourceType: AccessControlResourceType.ErrorTracking,
    minimumAccessLevel: AccessControlLevel.Viewer,
}

describe('matchesSettingAccessControl', () => {
    it.each([
        ['no gate is always allowed', undefined, undefined, true],
        [
            'no gate ignores access levels',
            undefined,
            { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.None },
            true,
        ],
        ['exact level satisfies', gate, { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Viewer }, true],
        [
            'higher level satisfies',
            gate,
            { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Editor },
            true,
        ],
        ['none level is denied', gate, { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.None }, false],
        [
            'missing resource entry is denied',
            gate,
            { [AccessControlResourceType.Insight]: AccessControlLevel.Manager },
            false,
        ],
        ['absent app context is denied', gate, undefined, false],
    ])('%s', (_name, accessControl, resourceAccessControl, expected) => {
        expect(matchesSettingAccessControl(accessControl as any, resourceAccessControl as any)).toBe(expected)
    })
})
