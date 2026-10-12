import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { OrganizationMemberType, UserType } from '~/types'

import { FilterOptions, ValueOption } from './commandKQuery'

/** Short words people type for a type, on top of its name and key. */
const TYPE_ALIASES: Record<string, string[]> = {
    feature_flag: ['flag', 'flags'],
    session_recording_playlist: ['playlist', 'replay', 'recording'],
    early_access_feature: ['eaf', 'beta'],
    workflows: ['workflow'],
    notebook: ['doc'],
}

let cachedTypeOptions: ValueOption[] | null = null

/** Every file system type from the product manifests, alphabetized. The manifests never change at runtime. */
const typeOptions = (): ValueOption[] => {
    if (cachedTypeOptions === null) {
        cachedTypeOptions = Object.entries(fileSystemTypes as Record<string, { name?: string; iconType?: string }>)
            .flatMap(([type, definition]) =>
                definition.name
                    ? [
                          {
                              value: type,
                              label: definition.name,
                              aliases: [
                                  type,
                                  definition.name.toLowerCase().replace(/\s+/g, '-'),
                                  ...(TYPE_ALIASES[type] ?? []),
                              ],
                              iconType: definition.iconType ?? type,
                          },
                      ]
                    : []
            )
            .sort((a, b) => a.label.localeCompare(b.label))
    }
    return cachedTypeOptions
}

const memberOption = (member: OrganizationMemberType): ValueOption => {
    const { first_name, last_name, email } = member.user
    return {
        value: email,
        label: [first_name, last_name].filter(Boolean).join(' ') || email,
        aliases: [first_name, last_name, email].filter((alias): alias is string => !!alias),
    }
}

/** `me` first, then everyone else in the organization. */
const userOptions = (members: OrganizationMemberType[], user: UserType | null): ValueOption[] => [
    { value: 'me', label: 'Me', aliases: user ? [user.first_name, user.email].filter(Boolean) : [] },
    ...members.filter((member) => member.user.uuid !== user?.uuid).map(memberOption),
]

export function buildFilterOptions(
    members: OrganizationMemberType[],
    user: UserType | null,
    folders: FileSystemEntry[] | null
): FilterOptions {
    return {
        is: typeOptions(),
        createdBy: userOptions(members, user),
        in: (folders ?? []).map((folder) => ({ value: folder.path, label: folder.path })),
        name: [],
    }
}
