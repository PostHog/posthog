import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import api from 'lib/api'
import { PersonType } from '~/types'

interface CohortUserSearchProps {
    cohortId: number
    isOpen: boolean
    onClose: () => void
}

export function CohortUserSearch({ cohortId, isOpen, onClose }: CohortUserSearchProps): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const [searchResults, setSearchResults] = useState<PersonType[]>([])
    const [isSearching, setIsSearching] = useState(false)
    const [selectedUsers, setSelectedUsers] = useState<PersonType[]>([])

    const searchUsers = async (term: string) => {
        if (!term.trim()) {
            setSearchResults([])
            return
        }

        setIsSearching(true)
        try {
            const response = await api.get(`/api/person/?search=${encodeURIComponent(term)}&limit=10`)
            setSearchResults(response.results || [])
        } catch (error) {
            lemonToast.error('Failed to search users')
        } finally {
            setIsSearching(false)
        }
    }

    const addUsersToCohort = async () => {
        if (selectedUsers.length === 0) return

        try {
            const distinctIds = selectedUsers.flatMap((user) => user.distinct_ids || [])
            await api.create(`/api/cohort/${cohortId}/add_users/`, {
                distinct_ids: distinctIds,
            })

            lemonToast.success(`Added ${selectedUsers.length} user${selectedUsers.length > 1 ? 's' : ''} to cohort`)
            setSelectedUsers([])
            onClose()
        } catch (error) {
            lemonToast.error('Failed to add users to cohort')
        }
    }

    const handleSearchChange = (value: string) => {
        setSearchTerm(value)
        if (value.trim()) {
            searchUsers(value)
        } else {
            setSearchResults([])
        }
    }

    const toggleUserSelection = (user: PersonType) => {
        setSelectedUsers((prev) =>
            prev.find((u) => u.id === user.id) ? prev.filter((u) => u.id !== user.id) : [...prev, user]
        )
    }

    const isUserSelected = (user: PersonType) => selectedUsers.some((u) => u.id === user.id)

    return (
        <LemonModal
            title="Add users to cohort"
            isOpen={isOpen}
            onClose={onClose}
            footer={
                <div className="flex justify-between items-center">
                    <span>
                        {selectedUsers.length} user{selectedUsers.length !== 1 ? 's' : ''} selected
                    </span>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" onClick={addUsersToCohort} disabled={selectedUsers.length === 0}>
                            Add to cohort
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium mb-2">Search users by email or distinct ID</label>
                    <LemonInput
                        value={searchTerm}
                        onChange={handleSearchChange}
                        placeholder="Enter email or distinct ID..."
                    />
                </div>

                {searchResults.length > 0 && (
                    <div className="border rounded-lg max-h-64 overflow-y-auto">
                        {searchResults.map((user) => (
                            <div
                                key={user.id}
                                className={`p-3 border-b last:border-b-0 cursor-pointer hover:bg-muted ${
                                    isUserSelected(user) ? 'bg-primary-highlight' : ''
                                }`}
                                onClick={() => toggleUserSelection(user)}
                            >
                                <div className="flex items-center justify-between">
                                    <div>
                                        <div className="font-medium">
                                            {user.name || user.properties?.email || user.distinct_ids?.[0] || 'Unknown'}
                                        </div>
                                        <div className="text-sm text-muted">
                                            {user.properties?.email && (
                                                <span className="mr-2">Email: {user.properties.email}</span>
                                            )}
                                            {user.distinct_ids?.[0] && <span>ID: {user.distinct_ids[0]}</span>}
                                        </div>
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={isUserSelected(user)}
                                        onChange={() => toggleUserSelection(user)}
                                        onClick={(e) => e.stopPropagation()}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {searchTerm && searchResults.length === 0 && !isSearching && (
                    <div className="text-center text-muted py-4">No users found matching "{searchTerm}"</div>
                )}
            </div>
        </LemonModal>
    )
}
