import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from './auth';

export const useAuthRedirect = (): void => {
  const {  isLoading, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    console.log({isLoading, user})
    if (!isLoading && !user) {
      console.log('Redirecting to login');
      router.push('/login');
    }
  }, [isLoading, user, router]);
};
