'use client'

import Link from 'next/link'
import { useState } from 'react'

import Header from '@/components/Header'
import { useAuth } from '@/lib/auth'
import { sampleFiles } from '@/lib/data'
import { useAuthRedirect } from '@/lib/hooks'
import { posthog } from '@/lib/posthog'
import { formatFileSize, getFileIcon } from '@/lib/utils'
import { HedgeboxFile } from '@/types'

export default function FilesPage(): React.JSX.Element {
    const { user } = useAuth()
    
    const [files, setFiles] = useState<HedgeboxFile[]>(sampleFiles)
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
    const [isUploading, setIsUploading] = useState(false)

    useAuthRedirect()

    if (!user) {return null}

    const handleFileUpload = async (): Promise<void> => {
        setIsUploading(true)
        const fileSize = Math.floor(Math.random() * 5000000)

        posthog.capture('uploaded_file', {
            file_type: 'image/jpeg',
            file_size_b: fileSize,
            used_mb: Math.floor((usedStorage + fileSize) / 1000000),
        })

        await new Promise((resolve) => setTimeout(resolve, 2000))

        const newFile: HedgeboxFile = {
            id: `file_${Date.now()}`,
            name: `hedgehog-adventure-${Date.now()}.jpg`,
            type: 'image/jpeg',
            size: fileSize,
            uploadedAt: new Date(),
        }

        setFiles((prev) => [newFile, ...prev])
        setIsUploading(false)
    }

    const trackFileAction = (action: string, file: HedgeboxFile): void => {
        posthog.capture(`${action}_file`, {
            file_type: file.type,
            file_size_b: file.size,
        })
    }

    const handleFileDelete = (fileId: string): void => {
        const file = files.find((f) => f.id === fileId)
        if (!file) {return}

        trackFileAction('deleted', file)
        setFiles((prev) => prev.filter((f) => f.id !== fileId))
        setSelectedFiles((prev) => {
            const newSet = new Set(prev)
            newSet.delete(fileId)
            return newSet
        })
    }

    const handleFileShare = (fileId: string): void => {
        const file = files.find((f) => f.id === fileId)
        if (!file) {return}

        trackFileAction('shared', file)
        setFiles((prev) =>
            prev.map((f) => (f.id === fileId ? { ...f, sharedLink: `https://hedgebox.net/files/${fileId}/shared` } : f))
        )
    }

    const handleFileDownload = (file: HedgeboxFile): void => {
        trackFileAction('downloaded', file)
    }

    const toggleFileSelection = (fileId: string): void => {
        setSelectedFiles((prev) => {
            const newSet = new Set(prev)
            if (newSet.has(fileId)) {
                newSet.delete(fileId)
            } else {
                newSet.add(fileId)
            }
            return newSet
        })
    }

    const usedStorage = files.reduce((total, file) => total + file.size, 0)
    const maxStorage = 1000000000 // 1GB
    const storagePercentage = (usedStorage / maxStorage) * 100

    const getStorageProgressClass = (): string => {
        if (storagePercentage > 90) {return 'progress-error'}
        if (storagePercentage > 70) {return 'progress-warning'}
        return 'progress-primary'
    }

    return (
        <div>
            <Header />

            <div className="container mx-auto px-4 py-8 max-w-7xl">
                {/* Welcome Header */}
                <div className="mb-8 animate-fade-in">
                    <div className="flex items-center justify-between flex-wrap gap-4">
                        <div>
                            <h1 className="text-4xl font-bold mb-2">Welcome back, {user.name.split(' ')[0]}! 🦔</h1>
                            <p className="text-base-content/70 text-lg">
                                Manage your hedgehog files with spike-proof security
                            </p>
                        </div>
                        <div className="stats shadow">
                            <div className="stat">
                                <div className="stat-title">Total files</div>
                                <div className="stat-value text-primary">{files.length}</div>
                            </div>
                            <div className="stat">
                                <div className="stat-title">Storage used</div>
                                <div className="stat-value text-secondary">{formatFileSize(usedStorage)}</div>
                                <div className="stat-desc">{storagePercentage.toFixed(1)}% of 1GB</div>
                            </div>
                        </div>
                    </div>

                    {/* Storage Progress */}
                    <div className="mt-6">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-medium">Storage usage</span>
                            <span className="text-sm text-base-content/70">{formatFileSize(usedStorage)} / 1GB</span>
                        </div>
                        <progress
                            className={`progress w-full ${getStorageProgressClass()}`}
                            value={storagePercentage}
                            max="100"
                        />
                    </div>
                </div>

                {/* Action Bar */}
                <div className="flex items-center justify-between mb-6 flex-wrap gap-4">
                    <div className="flex items-center space-x-4">
                        <button
                            onClick={handleFileUpload}
                            className={`btn btn-primary ${isUploading ? 'loading' : ''}`}
                            disabled={isUploading}
                        >
                            {isUploading ? 'Uploading...' : '📤 Upload file'}
                        </button>

                        {selectedFiles.size > 0 && (
                            <div className="flex items-center space-x-2">
                                <span className="text-sm text-base-content/70">{selectedFiles.size} selected</span>
                                <button
                                    className="btn btn-error btn-sm"
                                    onClick={() => {
                                        selectedFiles.forEach((fileId) => handleFileDelete(fileId))
                                    }}
                                >
                                    🗑️ Delete
                                </button>
                                <button
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => {
                                        selectedFiles.forEach((fileId) => handleFileShare(fileId))
                                    }}
                                >
                                    📤 Share
                                </button>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center space-x-2">
                        <div className="join">
                            <button
                                className={`btn btn-sm join-item ${viewMode === 'grid' ? 'btn-active' : ''}`}
                                onClick={() => setViewMode('grid')}
                            >
                                🔢 Grid
                            </button>
                            <button
                                className={`btn btn-sm join-item ${viewMode === 'list' ? 'btn-active' : ''}`}
                                onClick={() => setViewMode('list')}
                            >
                                🗒️ List
                            </button>
                        </div>
                    </div>
                </div>

                {/* Files Display */}
                {files.length === 0 ? (
                    <div className="text-center py-20 animate-fade-in">
                        <div className="text-8xl mb-4">📁</div>
                        <h3 className="text-2xl font-bold mb-2">No files yet</h3>
                        <p className="text-base-content/70 mb-6">Upload your first hedgehog files to get started!</p>
                        <button onClick={handleFileUpload} className="btn btn-primary btn-lg">
                            📤 Upload Your First File
                        </button>
                    </div>
                ) : viewMode === 'grid' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 animate-fade-in">
                        {files.map((file) => (
                            <Link
                                key={file.id}
                                href={`/files/${file.id}`}
                                className={`card bg-base-100 shadow-md hover:shadow-lg transition-all duration-300 cursor-pointer group ${
                                    selectedFiles.has(file.id) ? 'ring-2 ring-primary' : ''
                                }`}
                            >
                                <div className="card-body p-4">
                                    <div className="flex items-start justify-between mb-3">
                                        <div className="text-4xl">{getFileIcon(file.type)}</div>
                                        <div className="flex items-center space-x-1">
                                            <input
                                                type="checkbox"
                                                className="checkbox checkbox-primary checkbox-sm"
                                                checked={selectedFiles.has(file.id)}
                                                onChange={(e) => {
                                                    e.stopPropagation()
                                                    toggleFileSelection(file.id)
                                                }}
                                            />
                                            <div className="dropdown dropdown-end">
                                                <div
                                                    tabIndex={0}
                                                    role="button"
                                                    className="btn btn-ghost btn-xs"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    ⋮
                                                </div>
                                                <ul
                                                    tabIndex={0}
                                                    className="dropdown-content z-[1] menu p-2 shadow bg-base-100 rounded-lg w-40"
                                                >
                                                    <li>
                                                        <Link href={`/files/${file.id}`}>👁 View</Link>
                                                    </li>
                                                    <li>
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handleFileDownload(file)
                                                            }}
                                                        >
                                                            📥 Download
                                                        </button>
                                                    </li>
                                                    <li>
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handleFileShare(file.id)
                                                            }}
                                                        >
                                                            🔗 Share
                                                        </button>
                                                    </li>
                                                    <li>
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                handleFileDelete(file.id)
                                                            }}
                                                            className="text-error"
                                                        >
                                                            🗑️ Delete
                                                        </button>
                                                    </li>
                                                </ul>
                                            </div>
                                        </div>
                                    </div>

                                    <h3 className="font-semibold text-sm truncate mb-2" title={file.name}>
                                        {file.name}
                                    </h3>

                                    <div className="text-xs text-base-content/70 space-y-1">
                                        <div>{formatFileSize(file.size)}</div>
                                        <div>{new Date(file.uploadedAt).toLocaleDateString()}</div>
                                        {file.sharedLink && (
                                            <div className="badge badge-secondary badge-xs">Shared</div>
                                        )}
                                    </div>
                                </div>
                            </Link>
                        ))}
                    </div>
                ) : (
                    <div className="overflow-x-auto animate-fade-in">
                        <table className="table table-zebra">
                            <thead>
                                <tr>
                                    <th>
                                        <input
                                            type="checkbox"
                                            className="checkbox checkbox-primary"
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setSelectedFiles(new Set(files.map((f) => f.id)))
                                                } else {
                                                    setSelectedFiles(new Set())
                                                }
                                            }}
                                        />
                                    </th>
                                    <th>Name</th>
                                    <th>Size</th>
                                    <th>Modified</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {files.map((file) => (
                                    <tr key={file.id} className="hover">
                                        <td>
                                            <input
                                                type="checkbox"
                                                className="checkbox checkbox-primary"
                                                checked={selectedFiles.has(file.id)}
                                                onChange={() => toggleFileSelection(file.id)}
                                            />
                                        </td>
                                        <td>
                                            <Link
                                                href={`/files/${file.id}`}
                                                className="flex items-center space-x-3 cursor-pointer"
                                            >
                                                <div className="text-2xl">{getFileIcon(file.type)}</div>
                                                <div>
                                                    <div className="font-bold hover:text-primary">{file.name}</div>
                                                    <div className="text-sm text-base-content/70">{file.type}</div>
                                                </div>
                                            </Link>
                                        </td>
                                        <td>{formatFileSize(file.size)}</td>
                                        <td>{new Date(file.uploadedAt).toLocaleDateString()}</td>
                                        <td>
                                            {file.sharedLink ? (
                                                <div className="badge badge-secondary">Shared</div>
                                            ) : (
                                                <div className="badge badge-ghost">Private</div>
                                            )}
                                        </td>
                                        <td>
                                            <div className="flex space-x-2">
                                                <Link
                                                    href={`/files/${file.id}`}
                                                    className="btn btn-ghost btn-xs"
                                                    title="View file"
                                                >
                                                    👁️
                                                </Link>
                                                <button
                                                    onClick={() => handleFileDownload(file)}
                                                    className="btn btn-ghost btn-xs"
                                                    title="Download file"
                                                >
                                                    📥
                                                </button>
                                                <button
                                                    onClick={() => handleFileShare(file.id)}
                                                    className="btn btn-ghost btn-xs"
                                                    title="Share file"
                                                >
                                                    🔗
                                                </button>
                                                <button
                                                    onClick={() => handleFileDelete(file.id)}
                                                    className="btn btn-ghost btn-xs text-error"
                                                    title="Delete file"
                                                >
                                                    🗑️
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    )
}
