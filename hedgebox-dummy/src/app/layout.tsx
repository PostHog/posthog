'use client';

import './globals.css';
import { useEffect } from 'react';
import { initPostHog } from '@/lib/posthog';
import { AuthProvider } from '@/lib/auth';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  useEffect(() => {
    initPostHog();
  }, []);

  return (
    <html lang="en" data-theme="hedgebox">
      <body>
        <AuthProvider>
          <div className="min-h-screen bg-base-100">
            {children}
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
