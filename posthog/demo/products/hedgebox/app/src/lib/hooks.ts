import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from './auth';

export const useAuthRedirect = (redirectTo: string = '/files', redirectFrom: string = '/login'): void => {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user && redirectTo) {
      router.push(redirectTo);
    } else if (!user && redirectFrom) {
      router.push(redirectFrom);
    }
  }, [user, router, redirectTo, redirectFrom]);
};
