// An id is a place in the list and a taken item leaves a hole, so the ids hog holds never move.

use crate::Failure;

pub struct Store<T> {
    kind: &'static str,
    items: Vec<Option<T>>,
}

impl<T> Store<T> {
    pub fn new(kind: &'static str) -> Self {
        Store {
            kind,
            items: Vec::new(),
        }
    }

    pub fn hold(&mut self, item: T) -> usize {
        self.items.push(Some(item));
        self.items.len() - 1
    }

    fn unknown(&self, id: usize) -> Failure {
        Failure::bad_request(format!("the worker holds no {} {id}", self.kind))
    }

    pub fn take(&mut self, id: usize) -> Result<T, Failure> {
        match self.items.get_mut(id).and_then(Option::take) {
            Some(item) => Ok(item),
            None => Err(self.unknown(id)),
        }
    }

    pub fn take_all(&mut self, ids: &[usize]) -> Result<Vec<T>, Failure> {
        let mut taken = Vec::with_capacity(ids.len());
        for (place, id) in ids.iter().enumerate() {
            match self.take(*id) {
                Ok(item) => taken.push(item),
                Err(failure) => {
                    self.put_back(&ids[..place], taken);
                    return Err(failure);
                }
            }
        }
        Ok(taken)
    }

    pub fn put_back(&mut self, ids: &[usize], items: Vec<T>) {
        for (id, item) in ids.iter().zip(items) {
            self.items[*id] = Some(item);
        }
    }
}
