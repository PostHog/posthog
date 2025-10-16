'use client'

import { useAuth } from '@/lib/auth'
import Link from 'next/link'
import { useState } from 'react'

export default function Header(): JSX.Element {
    const { user, logout } = useAuth()
    const [isProfileOpen, setIsProfileOpen] = useState(false)

    const handleLogout = (): void => {
        logout()
        setIsProfileOpen(false)
    }

    const getAvatarUrl = (): string =>
        user?.avatar || `https://api.dicebear.com/7.x/adventurer/svg?seed=${user?.email}&backgroundColor=1e40af`

    const navLinks = user
        ? [{ href: '/files', icon: '📁', text: 'Files' }]
        : [
              { href: '/pricing', icon: '📊', text: 'Pricing' },
              { href: '/mariustechtips', icon: '📝', text: 'Blog' },
              { href: '/login', icon: '🔑', text: 'Log in' },
          ]

    const userMenuItems = [
        { href: '/account/settings', icon: '⚙️', text: 'Account Settings' },
        { href: '/account/billing', icon: '💳', text: 'Billing' },
        { href: '/account/team', icon: '👥', text: 'Team' },
    ]

    return (
        <div className="navbar bg-base-100/95 backdrop-blur-md shadow-lg border-b border-base-200/50 sticky top-0 z-50">
            <div className="navbar-start">
                {/* Mobile menu */}
                <div className="dropdown">
                    <div
                        tabIndex={0}
                        role="button"
                        className="btn btn-ghost lg:hidden hover:bg-primary/10 transition-colors"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M4 6h16M4 12h16M4 18h16"
                            />
                        </svg>
                    </div>
                    <ul
                        tabIndex={0}
                        className="menu menu-sm dropdown-content mt-3 z-[1] p-2 bg-base-100 rounded-box w-52 border border-base-200"
                    >
                        {navLinks.map((link) => (
                            <li key={link.href}>
                                <Link href={link.href} className="hover:bg-primary/10 rounded-lg">
                                    {link.icon} {link.text}
                                </Link>
                            </li>
                        ))}
                        {!user && (
                            <li className="pt-2">
                                <Link href="/signup" className="btn btn-primary btn-sm">
                                    ✨ Sign up
                                </Link>
                            </li>
                        )}
                        {user && (
                            <>
                                {userMenuItems.map((item) => (
                                    <li key={item.href}>
                                        <Link href={item.href} className="hover:bg-primary/10 rounded-lg">
                                            {item.icon} {item.text}
                                        </Link>
                                    </li>
                                ))}
                                <li>
                                    <button onClick={handleLogout} className="hover:bg-error/10 text-error rounded-lg">
                                        🚪 Log out
                                    </button>
                                </li>
                            </>
                        )}
                    </ul>
                </div>

                {/* Logo */}
                <Link href="/" className="btn btn-ghost text-xl hover:bg-primary/10 transition-all duration-300 group">
                    <div className="w-7 h-7 bg-primary rounded-lg flex items-center justify-center group-hover:scale-105 transition-transform">
                        <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                        </svg>
                    </div>
                    <span className="font-bold">Hedgebox</span>
                </Link>
            </div>

            <div className="navbar-end">
                <div className="hidden lg:flex items-center space-x-1">
                    {navLinks.map((link) => (
                        <Link
                            key={link.href}
                            href={link.href}
                            className="btn btn-ghost hover:bg-primary/10 transition-colors"
                        >
                            {link.icon} {link.text}
                        </Link>
                    ))}
                    {!user && (
                        <Link href="/signup" className="btn btn-primary hover:scale-105 transition-transform">
                            ✨ Sign up
                        </Link>
                    )}
                </div>
                {user && (
                    <div className="hidden lg:flex items-center space-x-4">
                        {/* User Profile Dropdown */}

                        <div className="dropdown dropdown-end">
                            <div
                                tabIndex={0}
                                role="button"
                                className="btn btn-ghost hover:bg-primary/10 transition-colors p-2"
                                onClick={() => setIsProfileOpen(!isProfileOpen)}
                            >
                                <div className="flex items-center space-x-2">
                                    <div className="avatar">
                                        <div className="w-8 h-8 rounded-full">
                                            <img src={getAvatarUrl()} alt={user.name} />
                                        </div>
                                    </div>
                                    <span className="hidden xl:block font-medium">{user.name.split(' ')[0]}</span>
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M19 9l-7 7-7-7"
                                        />
                                    </svg>
                                </div>
                            </div>

                            <ul
                                tabIndex={0}
                                className="dropdown-content z-[1] menu p-3 shadow-xl bg-base-100 rounded-box w-64 border border-base-200 mt-2"
                            >
                                <li className="mb-2">
                                    <div className="flex items-center space-x-3 p-2 rounded-lg bg-primary/5">
                                        <div className="avatar">
                                            <div className="w-10 h-10 rounded-full">
                                                <img src={getAvatarUrl()} alt={user.name} />
                                            </div>
                                        </div>
                                        <div>
                                            <div className="font-semibold text-sm">{user.name}</div>
                                            <div className="text-xs text-base-content/70">{user.email}</div>
                                            <div className="badge badge-primary badge-xs mt-1">{user.plan}</div>
                                        </div>
                                    </div>
                                </li>
                                {userMenuItems.map((item) => (
                                    <li key={item.href}>
                                        <Link href={item.href} className="hover:bg-primary/10 rounded-lg">
                                            {item.icon} {item.text}
                                        </Link>
                                    </li>
                                ))}
                                <div className="divider my-1" />
                                <li>
                                    <button onClick={handleLogout} className="hover:bg-error/10 text-error rounded-lg">
                                        🚪 Log out
                                    </button>
                                </li>
                            </ul>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
